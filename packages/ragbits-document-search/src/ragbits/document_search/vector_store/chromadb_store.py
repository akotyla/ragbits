from hashlib import sha256
from typing import Literal, Optional, Union, List

try:
    import chromadb

    HAS_CHROMADB = True
except ImportError:
    HAS_CHROMADB = False

from ragbits.core.embeddings.base import Embeddings
from ragbits.document_search.vector_store.in_memory import InMemoryVectorStore, VectorDBEntry


class ChromaDBStore(InMemoryVectorStore):
    """Class that stores text embeddings using [Chroma](https://docs.trychroma.com/)"""

    def __init__(
        self,
        index_name: str,
        chroma_client: chromadb.ClientAPI,
        embedding_function: Union[Embeddings, chromadb.EmbeddingFunction],
        max_distance: Optional[float] = None,
        distance_method: Literal["l2", "ip", "cosine"] = "l2",
    ):
        """
        Initializes the ChromaDBStore with the given parameters.

        Args:
            index_name (str): The name of the index.
            chroma_client (chromadb.ClientAPI): The ChromaDB client.
            embedding_function (Union[Embeddings, chromadb.EmbeddingFunction]): The embedding function.
            max_distance (Optional[float], default=None): The maximum distance for similarity.
            distance_method (Literal["l2", "ip", "cosine"], default="l2"): The distance method to use.
        """
        if not HAS_CHROMADB:
            raise ImportError("You need to install the 'ragbits-document-search[chromadb]' extra requirement of  to use LiteLLM embeddings models")

        super().__init__()
        self.index_name = index_name
        self.chroma_client = chroma_client
        self.embedding_function = embedding_function
        self.max_distance = max_distance

        self._metadata = {"hnsw:space": distance_method}

    def _get_chroma_collection(self) -> chromadb.Collection:
        """
        Based on the selected embedding_function, chooses how to retrieve the ChromaDB collection.
        If the collection doesn't exist, it creates one.

        Returns:
            chromadb.Collection: Retrieved collection
        """
        if isinstance(self.embedding_function, Embeddings):
            return self.chroma_client.get_or_create_collection(name=self.index_name, metadata=self._metadata)

        return self.chroma_client.get_or_create_collection(
            name=self.index_name,
            metadata=self._metadata,
            embedding_function=self.embedding_function,
        )

    def _return_best_match(self, retrieved: dict) -> Optional[str]:
        """
        Based on the retrieved data, returns the best match or None if no match is found.

        Args:
            retrieved (dict): Retrieved data, with a column-first format

        Returns:
            Optional[str]: The best match or None if no match is found
        """
        if self.max_distance is None or retrieved["distances"][0][0] <= self.max_distance:
            return retrieved["documents"][0][0]

        return None

    async def store(self, entries: List[VectorDBEntry]) -> None:
        """
        Stores entries in the ChromaDB collection.

        Args:
            entries (List[VectorDBEntry]): The entries to store.
        """
        formatted_data = [
            {
                "text": entry.vector,
                "metadata": {
                    "key": entry.key,
                    "metadata": entry.metadata,
                },
            }
            for entry in entries
        ]
        await self._store(formatted_data)

    async def _store(self, data: List[dict]) -> None:
        """
        Fills chroma collection with embeddings of provided string. As the id uses hash value of the string.

        Args:
            data (List[dict]): The data to store.
        """
        ids = [sha256(item["text"].encode("utf-8")).hexdigest() for item in data]
        texts = [item["text"] for item in data]
        metadata = [item["metadata"] for item in data]

        collection = self._get_chroma_collection()

        if isinstance(self.embedding_function, Embeddings):
            embeddings = await self.embedding_function.embed_text(texts)
            collection.add(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadata)
        else:
            collection.add(ids=ids, documents=texts, metadatas=metadata)

    async def retrieve(self, vector: List[float], k: int = 5) -> List[VectorDBEntry]:
        """
        Retrieves entries from the ChromaDB collection.

        Args:
            vector (List[float]): The vector to query.
            k (int, default=5): The number of entries to retrieve.

        Returns:
            List[VectorDBEntry]: The retrieved entries.
        """
        collection = self._get_chroma_collection()
        query_result = collection.query(query_embeddings=[vector], n_results=k)

        entries = []
        for doc, meta in zip(query_result.get("documents"), query_result.get("metadatas")):
            entry = VectorDBEntry(
                key=meta[0].get("key"),
                vector=doc[0],
                metadata=meta[0].get("metadata"),
            )
            entries.append(entry)
        return entries

    async def find_similar(self, text: str) -> Optional[str]:
        """
        Finds the most similar text in the chroma collection or returns None if the most similar text
        has distance bigger than `self.max_distance`.

        Args:
            text (str): The text to find similar to.

        Returns:
            Optional[str]: The most similar text or None if no similar text is found.
        """

        collection = self._get_chroma_collection()

        if isinstance(self.embedding_function, Embeddings):
            embedding = await self.embedding_function.embed_text([text])
            retrieved = collection.query(query_embeddings=embedding, n_results=1)
        else:
            retrieved = collection.query(query_texts=[text], n_results=1)

        return self._return_best_match(retrieved)

    def __repr__(self) -> str:
        """
        Returns the string representation of the object.

        Returns:
            str: The string representation of the object.
        """
        return f"{self.__class__.__name__}(index_name={self.index_name})"