from ai.config import AIConfig
from ai.rag.vectordb import QdrantVectorStore

def inspect_db():
    config = AIConfig.load()
    store = QdrantVectorStore(
        persist_path=config.rag.qdrant_persist_path,
        collection_name=config.rag.qdrant_collection_name
    )
    
    # Access the underlying qdrant client library directly from your store layer
    client = store.client
    collection_info = client.get_collection(config.rag.qdrant_collection_name)
    
    print(f"Collection Name: {config.rag.qdrant_collection_name}")
    print(f"Total Vectors stored: {collection_info.points_count}")
    
    if collection_info.points_count > 0:
        # Fetch just 1 scrolling point metadata and payload
        results = client.scroll(
            collection_name=config.rag.qdrant_collection_name,
            limit=1,
            with_payload=True,
            with_vectors=True
        )
        points, _ = results
        if points:
            point = points[0]
            print("\n" + "="*50)
            print("--- SAMPLE POINT RAG DATA DATA ---")
            print(f"ID: {point.id}")
            print(f"\nPayload (The chunks mapped logic):")
            for k, v in point.payload.items():
                print(f"   [{k}]: {str(v)[:200]}...") # Truncate text block printing for terminal sanity
            
            print(f"\nVector size (dimensions from Azure): {len(point.vector)}")
            print(f"Vector preview (first 5 math floats): {point.vector[:5]} ...")
            print("="*50 + "\n")

if __name__ == '__main__':
    inspect_db()
