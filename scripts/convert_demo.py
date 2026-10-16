"""Transcode captured WebM to MP4 with OpenCV's installed FFmpeg backend."""
from pathlib import Path
import cv2,json
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'artifacts/demo/Roomwise_demo.webm'
capture=cv2.VideoCapture(str(p))
if not capture.isOpened():raise RuntimeError('Recorded video cannot be decoded')
fps=capture.get(cv2.CAP_PROP_FPS) or 25
width,height=int(capture.get(3)),int(capture.get(4))
dst=p.with_suffix('.mp4');writer=cv2.VideoWriter(str(dst),cv2.VideoWriter_fourcc(*'mp4v'),fps,(width,height))
if not writer.isOpened():raise RuntimeError('MP4 encoder unavailable')
n=0
while True:
 ok,frame=capture.read()
 if not ok:break
 writer.write(frame);n+=1
writer.release();capture.release()
result={'frames':n,'fps':fps,'width':width,'height':height,'durationSeconds':n/fps,'bytes':dst.stat().st_size,'codec':'mp4v','audio':False,'content':'real application recording with on-screen captions'}
(dst.parent/'video_info.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
