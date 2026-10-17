import sys, pathlib
from oasis.agent.llm import LiveLLM, VisionExtractor, VisionUnavailable
d = pathlib.Path(sys.argv[1]); llm = LiveLLM(); v = VisionExtractor(llm)
for n in ("i2_chinese", "i3_photo", "i4_blurry", "i5_inject", "i6_wrongacct"):
    print("=====", n)
    try: print(v.to_text((d / (n + ".png")).read_bytes()))
    except VisionUnavailable as e: print("HOLD:", e)
print("calls", getattr(llm, "calls", "?"))
