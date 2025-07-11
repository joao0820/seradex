from docx import Document
from docx.opc.exceptions import PackageNotFoundError
import tiktoken
import boto3
from io import BytesIO
import os
import zipfile
import xml.etree.ElementTree as ET
import re
import olefile  # For .doc files
from docx2python import docx2python  # Alternative docx parser
import warnings
from typing import List, Tuple, Dict
from dotenv import load_dotenv

load_dotenv()

warnings.filterwarnings("ignore", category=UserWarning)

def get_required_env(name: str) -> str:
    """Get required environment variable or raise error"""
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value

def read_word_documents() -> List[Tuple[str, List[str], List[str]]]:
    """
    Processes all Word documents (.doc, .docx) and their summaries from S3
    Returns: List of (original_filename, original_chunks, summary_chunks)
    """
    try:
        # Initialize S3 client
        s3 = boto3.client('s3',
            region_name=get_required_env("AWS_REGION"),
            aws_access_key_id=get_required_env("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=get_required_env("AWS_SECRET_ACCESS_KEY")
        )
        bucket = get_required_env("AWS_S3_BUCKET_NAME")
        print("S3 client initialized" , flush=True)
    except Exception as e:
        print(f"Initialization failed: {e}")
        return []

    # Get all Word files and organize into pairs
    file_pairs = organize_files(s3, bucket)
    print("Document processing started" , flush=True)
    # Process all pairs
    documents = []
    for original_name, files in file_pairs.items():
        original_chunks = process_file(s3, bucket, files['original'])
        summary_chunks = process_file(s3, bucket, files['summary']) if files['summary'] else []
        documents.append((original_name, original_chunks, summary_chunks))
    print(f"Processed {len(documents)} documents")
    return documents

def organize_files(s3, bucket: str) -> Dict[str, Dict[str, str]]:
    """Organize files into original-summary pairs with correct extension handling"""
    file_pairs = {}
    
    # First pass: collect all files
    all_files = []
    paginator = s3.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get('Contents', []):
            key = obj['Key']
            if key.lower().endswith(('.doc', '.docx')):
                all_files.append(key)
    
    # Second pass: create proper pairings
    for filename in all_files:
        # Handle summary files
        if filename.lower().endswith('_summary.docx'):
            # Remove '_summary.docx' and try to find matching original
            original_candidate = filename[:-len('_summary.docx')]
            
            # Look for original with either .doc or .docx extension
            original_name = None
            for ext in ['.doc', '.docx']:
                if f"{original_candidate}{ext}" in all_files:
                    original_name = f"{original_candidate}{ext}"
                    break
            
            if original_name:
                file_pairs.setdefault(original_name, {'original': None, 'summary': None})['summary'] = filename
        else:
            # This is an original file, check if it has a summary
            base_name = os.path.splitext(filename)[0]  # Remove extension
            summary_name = f"{base_name}_summary.docx"
            if summary_name in all_files:
                file_pairs.setdefault(filename, {'original': None, 'summary': None})['summary'] = summary_name
            file_pairs.setdefault(filename, {'original': None, 'summary': None})['original'] = filename
    
    return file_pairs
    
def process_file(s3, bucket: str, s3_key: str) -> List[str]:
    """Process a single file (.doc or .docx)"""
    if not s3_key:
        return []
    
    try:
        # Get file from S3
        file_obj = s3.get_object(Bucket=bucket, Key=s3_key)
        file_bytes = file_obj['Body'].read()
        
        if s3_key.lower().endswith('.docx'):
            return process_docx(file_bytes, s3_key)
        elif s3_key.lower().endswith('.doc'):
            return process_doc(file_bytes, s3_key)
        else:
            return [f"UNSUPPORTED_FORMAT:{s3_key}"]
    except Exception as e:
        print(f"Failed to process {s3_key}: {e}")
        return [f"ERROR:{s3_key}:{str(e)}"]

def process_docx(file_bytes: bytes, s3_key: str) -> List[str]:
    """Process .docx file with multiple fallback methods"""
    # Method 1: python-docx
    try:
        doc = Document(BytesIO(file_bytes))
        text = '\n'.join([para.text for para in doc.paragraphs if para.text])
        if text.strip():
            return split_text_into_chunks(text)
    except Exception:
        pass
    
    # Method 2: docx2python
    try:
        with docx2python(BytesIO(file_bytes)) as docx_content:
            text = docx_content.text
            return split_text_into_chunks(text)
    except Exception:
        pass
    
    # Method 3: Direct XML extraction
    try:
        with zipfile.ZipFile(BytesIO(file_bytes)) as z:
            with z.open('word/document.xml') as f:
                xml_content = f.read()
                root = ET.fromstring(xml_content)
                namespaces = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                text = ' '.join([elem.text for elem in root.findall('.//w:t', namespaces) if elem.text])
                return split_text_into_chunks(text)
    except Exception:
        pass
    print(f"DOCX processing failed for {s3_key}")
    return [f"DOCX_PROCESSING_FAILED:{s3_key}"]

def process_doc(file_bytes: bytes, s3_key: str) -> List[str]:
    """Process .doc file using olefile"""
    try:
        if not olefile.isOleFile(BytesIO(file_bytes)):
            return [f"INVALID_DOC_FILE:{s3_key}"]
        
        with olefile.OleFileIO(BytesIO(file_bytes)) as ole:
            if ole.exists('WordDocument'):
                stream = ole.openstream('WordDocument')
                data = stream.read()
                text = data.decode('utf-8', errors='ignore')
                text = re.sub(r'[\x00-\x1F\x7F-\xFF]', ' ', text)  # Clean binary chars
                text = re.sub(r'\s+', ' ', text).strip()
                return split_text_into_chunks(text) if text else [f"EMPTY_DOC:{s3_key}"]
        return [f"NO_TEXT_IN_DOC:{s3_key}"]
    except Exception as e:
        print(f"DOC processing failed for {s3_key}: {e}")
        return [f"DOC_PROCESSING_FAILED:{s3_key}"]

def split_text_into_chunks(text: str, chunk_size: int = 500) -> List[str]:
    """Split text into chunks using tiktoken or fallback"""
    try:
        tokenizer = tiktoken.get_encoding("cl100k_base")
        tokens = tokenizer.encode(text)
        return [tokenizer.decode(tokens[i:i + chunk_size]) 
                for i in range(0, len(tokens), chunk_size)]

    except:
        return [text[i:i + chunk_size*4] for i in range(0, len(text), chunk_size*4)]

    # for original_name, original_chunks, summary_chunks in documents:
    #     print(f"Original: {original_name}, Chunks: {len(original_chunks)}, Summary Chunks: {len(summary_chunks)}")