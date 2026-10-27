"""Stream-extract Ollama tar.zst — CPU-only parts, skip huge GPU libs."""
import tarfile
import zstandard
import os

SRC = "/tmp/ollama.tar.zst"
DST = "/home/z/my-project/ollama"
os.makedirs(DST, exist_ok=True)

def wanted(name: str) -> bool:
    n = name.lstrip("./").lower()
    # Skip ONLY the huge GPU stacks (no GPU on this box)
    if "cuda" in n or "rocm" in n:
        return False
    return True

extracted = []
skipped_gpu = 0
dctx = zstandard.ZstdDecompressor()
with open(SRC, "rb") as fh:
    with dctx.stream_reader(fh) as reader:
        # r| = streaming mode, no seek needed
        with tarfile.open(fileobj=reader, mode="r|") as tf:
            for member in tf:
                if member.isdir():
                    continue
                if wanted(member.name):
                    tf.extract(member, DST)
                    extracted.append(member.name)
                else:
                    skipped_gpu += 1

total = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(DST) for f in fs)
print(f"extracted {len(extracted)} files, skipped {skipped_gpu} GPU/heavy files")
print(f"total size on disk: {total/1024/1024:.0f} MB")
for f in extracted[:8]:
    print("  ", f)
print("   ...")
