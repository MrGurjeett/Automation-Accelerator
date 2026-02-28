from ai.config import AIConfig
from ai.rag.vectordb import QdrantVectorStore, VectorDocument
from ai.clients.azure_openai_client import AzureOpenAIClient
from ai.rag.embedder import EmbeddingService

config = AIConfig.load()
store = QdrantVectorStore(
    persist_path=config.rag.qdrant_persist_path,
    collection_name=config.rag.qdrant_collection_name
)

# Test Document
doc1 = VectorDocument(
    id="test-doc-01",
    text="def click_login(self, page):\n    page.locator('button#login').click()",
    metadata={"source": "test", "type": "function"},
    embedding=[]
)

# Get Embedding from Azure!
client = AzureOpenAIClient(config.azure_openai)
embedder = EmbeddingService(client)
doc1.embedding = embedder.embed_texts([doc1.text])[0]

print(store.upsert([doc1]))
print("Inserted 1 node to Local DB!")
