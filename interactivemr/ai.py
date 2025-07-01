import os
import google.generativeai as genai
from dotenv import load_dotenv

class GeminiAI:
    """A class to handle interactions with the Gemini API."""

    def __init__(self):
        load_dotenv()
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY must be set in your .env file.")
        genai.configure(api_key=api_key)
        self.model = 'models/embedding-001'
        self.learned_embeddings = [] # Simple in-memory storage for now

    def get_embedding(self, text: str) -> list[float]:
        """
        Generates an embedding for a given text.

        Args:
            text: The text to embed.

        Returns:
            The embedding vector.
        """
        try:
            result = genai.embed_content(model=self.model, content=text)
            return result['embedding']
        except Exception as e:
            print(f"Error getting embedding: {e}")
            return []

    def learn_chunk(self, chunk_text: str, comment: str = None):
        """
        Learns a diff chunk by storing its embedding.

        Args:
            chunk_text: The text of the diff chunk.
            comment: An optional comment associated with the chunk.
        """
        embedding = self.get_embedding(chunk_text)
        if embedding:
            self.learned_embeddings.append({
                "embedding": embedding,
                "comment": comment
            })
            print("Successfully learned new chunk.")

    def find_similar_chunk(self, chunk_text: str, threshold: float = 0.8) -> dict | None:
        """
        Finds a similar learned chunk.

        Args:
            chunk_text: The text of the new chunk to compare.
            threshold: The similarity threshold.

        Returns:
            The learned chunk if a similar one is found, otherwise None.
        """
        import numpy as np

        if not self.learned_embeddings:
            return None

        new_embedding = self.get_embedding(chunk_text)
        if not new_embedding:
            return None

        for learned in self.learned_embeddings:
            # Using dot product for similarity, assuming embeddings are normalized
            similarity = np.dot(new_embedding, learned['embedding'])
            if similarity > threshold:
                print(f"Found similar chunk with similarity: {similarity:.2f}")
                return learned
        
        return None
