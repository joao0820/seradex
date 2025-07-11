import pyodbc
import os
from docx import Document
# Connection parameters

# Establish connection
conn_str = (
    'DRIVER={ODBC Driver 17 for SQL Server};'
    'SERVER=10.10.12.5,1433;'
    'DATABASE=_sxDocumentManager;'
    'UID=pyuser;'
    'PWD=StrongPassword123!;'
    'TrustServerCertificate=yes;'
)
    
output_dir = "documents"
os.makedirs(output_dir, exist_ok=True)

# Create a cursor
try:
    conn = pyodbc.connect(conn_str)
    print("Connection successful!")

    cursor = conn.cursor()
    cursor.execute("SELECT TOP 100 DocumentName, Summary, DocContent, Extension FROM dbo.DocumentRepository")  # Replace with a real table
    row_count = 0
    for row in cursor.fetchall():
        row_count += 1
        print(f"DocumentName: {row.DocumentName}, Summary: {row.Summary}, DocContent: {row.DocContent[:50]}...")

        document_name = row.DocumentName
        summary = row.Summary
        doc_content = row.DocContent
        extension = row.Extension
        
        # Save the document content to a file
        if extension.lower() == '.docx':
            doc_path = os.path.join(output_dir, document_name)
            with open(doc_path, 'wb') as f:
                f.write(doc_content)
            print(f"Document saved: {doc_path}")
        else:
            print(f"Unsupported file type: {extension}")

    cursor.close()
    conn.close()

except Exception as e:
    print("Connection failed:", e)