# STALL (stretch): an identity drop-probe stops a mid-pipeline link while upstream keeps flowing.
BAD='videotestsrc is-live=true ! video/x-raw,format=NV12,width=1280,height=720,framerate=30/1 ! nvvidconv ! video/x-raw(memory:NVMM) ! identity drop-probability=1.0 ! nvv4l2h264enc ! h264parse ! fakesink sync=false'
GOOD='videotestsrc is-live=true ! video/x-raw,format=NV12,width=1280,height=720,framerate=30/1 ! nvvidconv ! video/x-raw(memory:NVMM) ! identity ! nvv4l2h264enc ! h264parse ! fakesink sync=false'
