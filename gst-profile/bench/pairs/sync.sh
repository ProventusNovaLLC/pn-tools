# SYNC: a live path into a sink with sync=true pays a full latency budget / drops on QoS.
BAD='videotestsrc is-live=true ! video/x-raw,format=NV12,width=1920,height=1080,framerate=30/1 ! nvvidconv ! video/x-raw(memory:NVMM) ! nvv4l2h264enc ! h264parse ! queue ! fakesink sync=true'
GOOD='videotestsrc is-live=true ! video/x-raw,format=NV12,width=1920,height=1080,framerate=30/1 ! nvvidconv ! video/x-raw(memory:NVMM) ! nvv4l2h264enc ! h264parse ! queue ! fakesink sync=false'
