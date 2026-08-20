# QUEUE: no thread boundary before the encoder; source, convert and encode share one streaming thread.
BAD='videotestsrc is-live=true ! video/x-raw,format=NV12,width=1920,height=1080,framerate=30/1 ! nvvidconv ! video/x-raw(memory:NVMM) ! nvv4l2h264enc ! h264parse ! fakesink sync=false'
GOOD='videotestsrc is-live=true ! video/x-raw,format=NV12,width=1920,height=1080,framerate=30/1 ! nvvidconv ! video/x-raw(memory:NVMM) ! queue ! nvv4l2h264enc ! h264parse ! fakesink sync=false'
