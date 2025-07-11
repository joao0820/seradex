from openai import OpenAI
from pinecone import Pinecone
from document_processor import read_word_documents
import os
import hashlib
from dotenv import load_dotenv

load_dotenv()

# Initialize clients
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def get_embedding(text):
    """Generate embedding using OpenAI"""
    response = client.embeddings.create(
        input=text,
        model="text-embedding-ada-002"
    )
    return response.data[0].embedding

def create_document_id(filename):
    """Create unique ID for document chunk"""
    return hashlib.md5(f"{filename}".encode()).hexdigest()

def process_word_documents(index_name):
    """Process all Word documents in a folder"""
    print("Processing Word documents..." , flush=True)
    documents = read_word_documents()
    print(len(documents), "documents found" , flush=True)
    index = pc.Index(index_name)
    

    for original_name, original_chunks, summary_chunks in documents:
        # Create doc ID using original filename
        filename = os.path.basename(original_name)
        doc_id = create_document_id(filename)
        source_url = f"https://{os.getenv('BASIC_SOURCE_URL')}/{original_name}"
        # Process original document chunks
        for chunk_id, chunk in enumerate(original_chunks):
            embedding = get_embedding(chunk)
            index.upsert(
                vectors=[{
                    "id": f"original_{doc_id}_{chunk_id}",
                    "values": embedding,
                    "metadata": {
                        "text": chunk,
                        "doc_id": doc_id,  
                        "source_url": source_url 
                    }
                }]
            )
        
        # Process summary chunks
        for chunk_id, chunk in enumerate(summary_chunks):
            embedding = get_embedding(chunk)
            index.upsert(
                vectors=[{
                    "id": f"summary_{doc_id}_{chunk_id}",
                    "values": embedding,
                    "metadata": {
                        "text": chunk,
                        "doc_id": doc_id,  # Same doc_id as the original
                        "linked_to": f"original_{doc_id}",
                        "source_url" : source_url 
                    }
                }]
            )
    
    print("All documents processed successfully!" , flush=True)

if __name__ == '__main__':
    # Create or connect to index
    index_name = os.getenv("PINECONE_INDEX_NAME")
    print("stated",  flush=True)
    # Process documents from 'documents' folder
    process_word_documents(index_name)
    print("Knowledge base populated successfully!")