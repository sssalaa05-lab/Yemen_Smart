"""Targeted extraction: llama-server + libllama* + libgomp* from Ollama tar.zst."""
import tarfile
import zstandard

SRC = "/tmp/ollama.tar.zst"
DST = "/home/z/my-project/ollama"

def wanted(name: str) -> bool:
    n = name.lstrip("./").lower()
    if "cuda" in n or "rocm" in n:
        return False
    keep = (
        "llama-server",
        "llama-quantize",
        "libllama",
        "libgomp",
        "libmtmd",
    )
    return any(k in n for k in keep)

done = []
dctx = zstandard.ZstdDecompressor()
with open(SRC, "rb") as fh:
    with dctx.stream_reader(fh) as reader:
        with tarfile.open(fileobj=reader, mode="r|") as tf:
            for member in tf:
                if member.isdir():
                    continue
                if wanted(member.name):
                    tf.extract(member, DST, filter="data")
                    done.append((member.name, member.size))

for name, size in done:
    print(f"{size/1024/1024:8.1f}MB  {name}")
