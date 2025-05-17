import logging

import pandas as pd

from mindsdb_sql.parser import ast

from mindsdb.integrations.libs.api_handler import APIHandler, APITable
from mindsdb.integrations.utilities.sql_utils import extract_comparison_conditions, project_dataframe

import semantic_kernel as sk
from semantic_kernel.connectors.ai.open_ai import OpenAITextEmbedding
from semantic_kernel.connectors.memory.qdrant import QdrantMemoryStore
import os
import asyncio
import concurrent.futures

from mindsdb.integrations.libs.response import (
    HandlerStatusResponse as StatusResponse,
    HandlerResponse as Response,
    RESPONSE_TYPE
)


class Qdrant(APITable):

    def __init__(self, name=None, **kwargs):
        super().__init__(name)
        self.kernel = self.initialize_kernel()

    def select(self, query: ast.Select) -> pd.DataFrame:
        conditions = extract_comparison_conditions(query.where)
        ask = ""
        memory_collection_name = "all"
        min_relevance_score = 0.77
        collections = self.get_collections()
        subcollections = list()
        for op, arg1, arg2 in conditions:
            if op == 'or':
                raise NotImplementedError(f'OR is not supported')

            if arg1 == 'ask':
                ask = str(arg2)

            if arg1 == 'collection':
                if op == 'like':
                    subcollections = [item for item in collections if str(arg2).lower() in item.lower()]
                memory_collection_name = str(arg2)

            if arg1 == 'min_relevance_score':
                min_relevance_score = float(arg2)

        if memory_collection_name.lower() != 'all':
            with concurrent.futures.ThreadPoolExecutor() as executor:
                results = list(
                    executor.map(lambda item: self.process_item(item, ask, query.limit.value, min_relevance_score, query),
                                 subcollections))

            # If you want to combine all DataFrames into one
            final_result = pd.concat(results, ignore_index=True)
            #final_result = final_result.loc[:, query.targets[0].parts[1]]
            return final_result

        else:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                results = list(
                    executor.map(lambda item: self.process_item(item, ask, query.limit.value, min_relevance_score, query),
                                 collections))

            # If you want to combine all DataFrames into one
            final_result = pd.concat(results, ignore_index=True)
            return final_result

    def process_item(self, item, ask, result_limit, min_relavance_score, query):
        memories = self.search_memory(item, ask, result_limit, min_relavance_score)
        df = self.memories_to_dataframe(memories)
        result = project_dataframe(df, query.targets, self.get_columns())
        return result
    def memories_to_dataframe(self, memories):
        # Initialize an empty dictionary to store the data
        data = {
            #'Id': [],
            'Text': [],
            #'Relevance': []
            # Add any other fields as needed
        }
        #data = columns

        # Iterate through the memories and extract the data
        for memory in memories:
            #data['Id'].append(memory.id)
            data['Text'].append(memory.text)
            #data['Relevance'].append(memory.relevance)
            # Extract any other fields as needed

        # Create a DataFrame from the dictionary
        df = pd.DataFrame(data)

        return df

    def get_columns(self):
        return [
            'text',
            #'relevance'
        ]

    def initialize_kernel(self):
        kernel = sk.Kernel()
        chatgpt_key = os.environ['chatgpt']

        self.qdrant_mem_store = QdrantMemoryStore(1536, "rs-win")
        embedding_service = OpenAITextEmbedding("text-embedding-ada-002", chatgpt_key)

        kernel.add_text_embedding_generation_service('ada', embedding_service)
        kernel.register_memory_store(self.qdrant_mem_store)

        return kernel

    def search_memory(self, collection_name, query, limit=5, min_relevance_score=0.77):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Run the asynchronous function and wait for the result
            memories = loop.run_until_complete(
                self.kernel.memory.search_async(
                    collection_name, query, limit, min_relevance_score
                )
            )
            return memories
        finally:
            loop.close()

    def get_collections(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Run the asynchronous function and wait for the result
            collections = loop.run_until_complete(
                self.qdrant_mem_store.get_collections_async()
            )
            return collections
        finally:
            loop.close()

class QdrantHandler(APIHandler):
    """A class for handling Qdrant.

    Attributes:

    """

    def __init__(self, name=None, **kwargs):
        super().__init__(name)

        self.api = None
        self.is_connected = True
        self.qdrant = Qdrant(self)
        self._register_table('qdrant', self.qdrant)

    def check_connection(self) -> StatusResponse:
        response = StatusResponse(False)
        response.success = True

        return response


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
