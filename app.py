import os
from openai import OpenAI
from pinecone import Pinecone
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize clients
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = Flask(__name__)

def get_embedding(text):
    """Generate embedding using OpenAI"""
    response = client.embeddings.create(
        input=text,
        model="text-embedding-ada-002"
    )
    return response.data[0].embedding

def generate_chat_response(query, context):
    """Generate response using OpenAI's chat model"""
    # sources_text = "\n".join([f"- {source}" for source in sources])

    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": f"Context: {context}\n\nQuestion: {query}\nAnswer:"},
        # {"role": "system", "content": f"Sources:\n{sources_text}"}
    ]
    
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=messages,
        temperature=0.7
    )
    
    return response.choices[0].message.content

@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    query = data.get('query', '').strip()
    
    if not query:
        return jsonify({"error": "Query is required"}), 400
    
    try:
        # Get embedding for query
        query_embedding = get_embedding(query)
        
        # Query Pinecone
        results = pc.Index(os.getenv("PINECONE_INDEX_NAME")).query(
            vector=query_embedding,
            top_k=3,
            include_metadata=True
        )
        # print(f"Query results: {results}")
        # Prepare context and sources
        context = []
        sources = set()
        docs = set()
        for match in results.matches:
            context.append(match.metadata['text'])
            sources.add("https://" + match.metadata['source_url'].split("https://")[-1])
            docs.add(match.metadata['doc_id'])
        print(sources)

        
        # Generate response
        response = generate_chat_response(query, "\n\n".join(context))
        
        return jsonify({
            "response": response,
            "sources": list(sources),
            "docs": list(docs)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)