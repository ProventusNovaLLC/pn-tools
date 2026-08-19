# SW: videoconvert used where nvvidconv exists (software element on a HW-capable path).
BAD='videotestsrc is-live=true ! video/x-raw,format=I420,width=1280,height=720,framerate=30/1 ! videoconvert ! video/x-raw,format=NV12 ! nvvidconv ! video/x-raw(memory:NVMM) ! nvv4l2h264enc ! h264parse ! fakesink sync=false'
GOOD='videotestsrc is-live=true ! video/x-raw,format=NV12,width=1280,height=720,framerate=30/1 ! nvvidconv ! video/x-raw(memory:NVMM) ! nvv4l2h264enc ! h264parse ! fakesink sync=false'
