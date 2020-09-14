# Copyright 2020 CDPedistas (see AUTHORS.txt)
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3, as published
# by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranties of
# MERCHANTABILITY, SATISFACTORY QUALITY, or FITNESS FOR A PARTICULAR
# PURPOSE.  See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# For further info, check  https://github.com/PyAr/CDPedia/


import array
import logging
import os
import pickle
import random
import sqlite3
from collections import defaultdict
from functools import lru_cache
import lzma as best_compressor  # zlib is faster, lzma has better ratio.

from src.armado import to3dirs
from src.utiles import ProgressBar

logger = logging.getLogger(__name__)

PAGE_SIZE = 512


def decompress_data(data):
    return pickle.loads(best_compressor.decompress(data))


class DocSet:
    """Data type to encode, decode & compute documents-id's sets."""
    SEPARATOR = 0xFF

    def __init__(self):
        self._docs_list = defaultdict(list)

    def append(self, docid, position):
        """Append an item to the docs_list."""
        self._docs_list[docid].append(position)

    def __len__(self):
        return len(self._docs_list)

    def __repr__(self):
        value = repr(self._docs_list).replace("[", "").replace("],", "|").replace("]})", "}")
        curly = value.index("{")
        value = value[curly:curly + 75]
        if not value.endswith("}"):
            value += " ..."
        return "<Docset: len={} {}>".format(len(self._docs_list), value)

    def __eq__(self, other):
        return self._docs_list == other._docs_list

    @staticmethod
    def delta_encode(ordered):
        """Compress an array of numbers into a bytes object."""
        result = array.array('B')
        add_to_result = result.append

        prev_doc = 0
        for doc in ordered:
            doc, prev_doc = doc - prev_doc, doc
            while True:
                b = doc & 0x7F
                doc >>= 7
                if doc:
                    # the number is not exhausted yet,
                    # store these 7b with the flag and continue
                    add_to_result(b | 0x80)
                else:
                    # we're done, store the remaining bits
                    add_to_result(b)
                    break

        return result.tobytes()

    @staticmethod
    def delta_decode(ordered):
        """Decode a compressed encoded bucket.

        - ordered is a bytes object, representing a byte's array
        - ctor is the final container
        - append is the callable attribute used to add an element into the ctor
        """
        result = []
        add_to_result = result.append

        prev_doc = doc = shift = 0

        for b in ordered:
            doc |= (b & 0x7F) << shift
            shift += 7

            if not (b & 0x80):
                # the sequence ended
                prev_doc += doc
                add_to_result(prev_doc)
                doc = shift = 0

        return result

    def encode(self):
        """Encode to store compressed inside the database."""
        if not self._docs_list:
            return ""
        docs_list = []
        for key, values in self._docs_list.items():
            docs_list.extend((key, value) for value in values)
        docs_list.sort()
        docs = [v[0] for v in docs_list]
        docs_enc = DocSet.delta_encode(docs)
        # if any score is greater than 255 or lesser than 1, it won't work
        position = [v[1] for v in docs_list]
        if any([x >= self.SEPARATOR for x in position]):
            raise ValueError("Positions can't be greater than 254.")
        position.append(self.SEPARATOR)
        position = array.array("B", position)
        return position.tobytes() + docs_enc

    @classmethod
    def decode(cls, encoded):
        """Decode a compressed docset."""
        docset = cls()
        if len(encoded) > 1:
            limit = encoded.index(cls.SEPARATOR)
            docsid = cls.delta_decode(encoded[limit + 1:])
            positions = array.array('B')
            positions.frombytes(encoded[:limit])
            docset._docs_list = defaultdict(list)
            for docid, position in zip(docsid, positions):
                docset._docs_list[docid].append(position)
        return docset


def open_connection(filename):
    """Connect and register data types and aggregate function."""
    # Register the adapter
    def adapt_docset(docset):
        return docset.encode()
    sqlite3.register_adapter(DocSet, adapt_docset)

    # Register the converter
    def convert_docset(s):
        return DocSet.decode(s)
    sqlite3.register_converter("docset", convert_docset)

    con = sqlite3.connect(filename, check_same_thread=False, detect_types=sqlite3.PARSE_COLNAMES)
    return con


def to_filename(title):
    """Compute the filename from the title."""
    tt = title.replace(" ", "_")
    if len(tt) >= 2:
        tt = tt[0].upper() + tt[1:]
    elif len(tt) == 1:
        tt = tt[0].upper()
    else:
        raise ValueError("Title must have at least one character")

    dir3, arch = to3dirs.get_path_file(tt)
    expected = os.path.join(dir3, arch)
    return expected


class Index:
    """Handle the index."""

    def __init__(self, directory):
        self._directory = directory
        keyfilename = os.path.join(directory, "index.sqlite")
        self.db = open_connection(keyfilename)
        self.db.executescript('''
            PRAGMA query_only = True;
            PRAGMA journal_mode = MEMORY;
            PRAGMA temp_store = MEMORY;
            PRAGMA synchronous = OFF;
            ''')

    def keys(self):
        """Returns an iterator over the stored keys."""
        cur = self.db.execute("SELECT word FROM tokens")
        return [row[0] for row in cur.fetchall()]

    def items(self):
        """Returns an iterator over the stored items."""
        sql = "select word, docsets as 'ds [docset]' from tokens"
        cur = self.db.execute(sql)
        for row in cur.fetchall():
            yield row[0], row[1]

    def values(self):
        """Returns an iterator over the stored values."""
        cur = self.db.execute("SELECT pageid, data FROM docs ORDER BY pageid")
        for row in cur.fetchall():
            decomp_data = decompress_data(row[1])
            for doc in decomp_data:
                yield doc

    @lru_cache(1)
    def __len__(self):
        """Compute the total number of docs in compressed pages."""
        sql = "Select pageid, data from docs order by pageid desc limit 1"
        cur = self.db.execute(sql)
        row = cur.fetchone()
        decomp_data = decompress_data(row[1])
        return row[0] * PAGE_SIZE + len(decomp_data)

    def random(self):
        """Returns a random value."""
        docid = random.randint(0, len(self) - 1)
        return self.get_doc(docid)

    def __contains__(self, key):
        """Returns if the key is in the index or not."""
        cur = self.db.execute("SELECT word FROM tokens where word = ?", (key,))
        if cur.fetchone():
            return True
        return False

    @lru_cache(1000)
    def _get_page(self, pageid):
        cur = self.db.execute("SELECT data FROM docs where pageid = ?", (pageid,))
        row = cur.fetchone()
        if row:
            decomp_data = decompress_data(row[0])
            return decomp_data
        return None

    def get_doc(self, docid):
        '''Returns one stored document item.'''
        page_id, rel_position = divmod(docid, PAGE_SIZE)
        data = self._get_page(page_id)
        if not data:
            return None
        row = data[rel_position]
        # if the html filename is marked as computable
        # do it and store in position 0.
        if row[0] is None:
            row[0] = to_filename(row[1])
        return row

    @classmethod
    def create(cls, directory, source):
        """Creates the index in the directory.
        The source must give path, page_score, title and
        a list of extracted words from title in an ordered fashion

        It must return the quantity of pairs indexed.
        """
        import pickletools
        import timeit

        class SQLmany:
            """Execute many INSERTs greatly improves the performance."""
            def __init__(self, name, sql, quantity):
                self.sql = sql
                self.name = name
                self.count = 0
                self.buffer = []
                self.progress_bar = ProgressBar(name, quantity)

            def append(self, data):
                """Append one data set to persist on db."""
                self.buffer.append(data)
                self.count += 1
                if self.count % PAGE_SIZE == 0:
                    self.persist()
                    self.buffer = []
                # self.count is the quantity of docs added
                # but it is the index that is returned
                # and it is zero based, hence one less.
                self.progress_bar.step(self.count)
                return self.count - 1

            def finish(self):
                """Finish the process and prints some data."""
                if self.buffer:
                    self.persist()
                self.progress_bar.finish(self.count)
                dict_stats[self.name] = self.count

            def persist(self):
                """Commit data to index."""
                database.executemany(self.sql, self.buffer)
                database.commit()

        class Compressed(SQLmany):
            """Creates the table of compressed documents information.

            The groups is PAGE_SIZE word_quant, pickled and compressed."""
            def persist(self):
                """Compress and commit data to index."""
                docs_data = []
                word_quants = array.array("B")
                for word_quant, data in self.buffer:
                    word_quants.append(word_quant)
                    docs_data.append(data)
                pickdata = pickletools.optimize(pickle.dumps(docs_data))
                comp_data = best_compressor.compress(pickdata)
                page_id = (self.count - 1) // PAGE_SIZE
                database.execute(self.sql, (page_id, word_quants.tobytes(), comp_data))
                database.commit()

        def create_database():
            """Creates de basic structure of new database."""
            script = """
                PRAGMA journal_mode = OFF;
                PRAGMA synchronous = OFF;
                CREATE TABLE tokens
                    (word TEXT,
                    docsets BLOB);
                CREATE TABLE docs
                    (pageid INTEGER PRIMARY KEY,
                    word_quants BLOB,
                    data BLOB);
                """

            database.executescript(script)

        def add_docs_keys(source, quantity):
            """Add docs and keys registers to db and its rel in memory."""
            idx_dict = defaultdict(DocSet)
            sql = "INSERT INTO docs (pageid, word_quants, data) VALUES (?, ?, ?)"
            docs_table = Compressed("Documents", sql, quantity)
            page_ant = -1

            for words, page_score, data in source:
                if page_ant > 0 and page_score > page_ant:
                    print("ant:", page_ant, " scr:", page_score)
                page_ant = page_score
                data = list(data) + [page_score]
                docid = docs_table.append((len(words), data))
                for idx, word in enumerate(words):
                    # item_score = max(1, 0.6 * word_sccores
                    idx_dict[word].append(docid, idx)

            docs_table.finish()
            return idx_dict

        def add_tokens_to_db(idx_dict):
            """Insert token words in the database."""
            sql_ins = "insert into tokens (word, docsets) values (?, ?)"
            token_store = SQLmany("Tokens", sql_ins, len(idx_dict))
            for word, docs_list in idx_dict.items():
                logger.debug("Word: %s %r" % (word, docs_list))
                dict_stats["Indexed"] += len(docs_list)
                token_store.append((word, docs_list))
            token_store.finish()

        def create_indexes():
            script = '''
                create index idx_words on tokens (word);
                vacuum;
                '''
            database.executescript(script)

        def order_source(source):
            """Load on memory dict to ensure ordered docs."""
            ordered_source = defaultdict(list)
            quant = 0
            for quant, (words, page_score, data) in enumerate(source):
                data = list(data)
                # see if html file name can be deduced
                # from the title. Mark using None
                if data[0] == to_filename(data[1]):
                    data[0] = None
                value = [words, page_score, data]
                ordered_source[page_score].append(value)
            return ordered_source, quant

        def gen_ordered(ordered_source):
            for score in sorted(ordered_source.keys(), reverse=True):
                for value in ordered_source[score]:
                    yield value

        logger.info("Indexing")
        initial_time = timeit.default_timer()
        dict_stats = defaultdict(int)
        keyfilename = os.path.join(directory, "index.sqlite")
        database = open_connection(keyfilename)
        create_database()
        ordered_source, quantity = order_source(source)
        idx_dict = add_docs_keys(gen_ordered(ordered_source), quantity)
        add_tokens_to_db(idx_dict)
        create_indexes()
        dict_stats["Total time"] = int(timeit.default_timer() - initial_time)
        # Finally, show some statistics.
        for k, v in dict_stats.items():
            logger.info("{:>20}:{}".format(k, v))
        return dict_stats["Indexed"]