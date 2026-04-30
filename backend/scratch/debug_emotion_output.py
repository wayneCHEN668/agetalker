# e:\MyDoc\APP\agetalker\backend\scratch\debug_emotion_output.py
import numpy as np
from funasr import AutoModel
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

model = AutoModel(model='iic/emotion2vec_plus_large', device='cpu')

# Create 1s dummy audio
audio = np.zeros(16000, dtype=np.float32)

print("Running inference...")
res = model.generate(
    input=audio,
    sample_rate=16000,
    granularity='utterance',
    extract_embedding=False
)

print("Result structure:")
print(res)

if res:
    print("res[0] keys:", res[0].keys())
    if 'scores' in res[0]:
        print("scores type:", type(res[0]['scores']))
        print("First score item:", res[0]['scores'][0])
        print("First score item type:", type(res[0]['scores'][0]))
