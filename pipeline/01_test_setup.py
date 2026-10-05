import sys

print("Cek setup chatbot skincare")


#cek semua libary
print("\nCek library...")
libraries =  [
    ("pandas", "pandas"),
    ("numpy", "numpy"),
    ("scikit-learn", "sklearn"),
    ("requests", "requests"),
    ("selenium", "selenium"),
    ("chromadb", "chromadb"),
    ("sentence-transformers", "sentence_transformers"),
    ("groq", "groq"),
    ("fastapi", "fastapi"),
    ("streamlit", "streamlit"),
    ("python-dotenv", "dotenv"),
    ("PySastrawi", "Sastrawi"),
    ("tqdm", "tqdm"),
]

semua_ok=True
for nama, modul in libraries:
    try:
        __import__(modul)
        print(f"✓ {nama}")
    except ImportError:
        print(f"{nama} belum terinstall, tuliskan {nama} di requirements.txt")
        semua_ok=False

#cek file.env and API key
print("\nCek Groq API key...")
try:
    from dotenv import load_dotenv
    import os
    load_dotenv()
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or api_key.startswith("gsk_xxx"):
        print("GROQ_API_KEY belum diisi di file .env")
        semua_ok=False
    else:
        print(f"API key ditemukan: {api_key[:12]}...")
except Exception as e:
    print(f"    ✗ Error: {e}")
    semua_ok = False

#tes koneksi Groq
if semua_ok:
    print("\nTes koneksi ke Groq API...")
    try:
        from groq import Groq
        client=Groq(api_key=os.getenv("GROQ_API_KEY"))
        resp=client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"user","content":" hanya balas dengan : Groq berjalan dengan baik"}],
            max_tokens=20
        )
        print(f"    ✓ Groq response:  {resp.choices[0].message.content}")
    except Exception as e:
        print(f"    ✗ Groq error: {e}")
        semua_ok = False

#tes koneksi ChromaDB
print("\n[5] Tes ChromaDB...")

try:
    import chromadb
    import shutil
    import gc
    import time

    test_path = "data/chroma_test"

    client = chromadb.PersistentClient(path=test_path)

    collection = client.get_or_create_collection("test")

    collection.add(
        ids=["1"],
        documents=["test dokumen"],
        embeddings=[[0.1] * 384]
    )

    result = collection.query(
        query_embeddings=[[0.1] * 384],
        n_results=1
    )

    assert result["documents"][0][0] == "test dokumen"

    # Tutup objek ChromaDB
    del collection
    del client

    gc.collect()
    time.sleep(2)

    try:
        shutil.rmtree(test_path)
    except:
        pass

    print("    ✓ ChromaDB OK")

except Exception as e:
    print(f"    ✗ ChromaDB error: {e}")
    semua_ok = False

