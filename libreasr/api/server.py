import argparse
from concurrent import futures
import time
import math
import logging
from pathlib import Path
import itertools
from multiprocessing import Process

import grpc

import libreasr.api.interfaces.libreasr_pb2 as ap
import libreasr.api.interfaces.libreasr_pb2_grpc as apg
from libreasr.lib.inference.imports import *
from libreasr.lib.inference.main import load_stuff
from libreasr.lib.inference.utils import load_config


# gRPC thread pool
WORKERS = 4


def log_print(*args, **kwargs):
    print("[api-server]", *args, **kwargs)


def get_settings(conf):
    downsample = None
    n_buffer = None
    for tfm in conf["transforms"]["stream"]:
        if tfm["name"] == "StackDownsample":
            downsample = tfm["args"]["downsample"]
        if tfm["name"] == "Buffer":
            n_buffer = tfm["args"]["n_buffer"]
    return downsample, n_buffer


class LibreASRServicer(apg.LibreASRServicer):
    def __init__(self, config_path, lang):
        from libreasr import LibreASR

        self.lang_name = lang
        self.l = LibreASR(self.lang_name, config_path=config_path)
        self.l.load_inference()

    def Transcribe(self, request, context):

        # tensorize
        aud, sr = request.data, request.sr
        aud = tensorize(aud)

        # print
        log_print(f"Transcribe(lang={self.lang_name}, sr={sr}, shape={aud.shape})")

        # tfms
        aud = AudioTensor(aud, sr)
        aud = self.x_tfm(aud)[0]

        # inference
        out = self.model.transcribe(aud)

        return ap.Transcript(data=out[0])

    def TranscribeStream(self, request_iterator, context):
        # peek at the first frame
        #  (for getting sr)
        frame = request_iterator.next()
        sr = frame.sr
        unpeeked = itertools.chain([frame], request_iterator)

        # inference
        for diff, now in self.l.stream(iter(unpeeked), sr=sr):
            yield ap.Transcript(data=diff)


def serve(config_path, lang):
    # bring up model
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=WORKERS))
    apg.add_LibreASRServicer_to_server(LibreASRServicer(config_path, lang), server)

    # load config
    conf = load_config(config_path, lang)

    # start gRPC server
    port = f"[::]:{conf['grpc_port']}"
    log_print("gRPC server starting on", port, "language", lang)
    server.add_insecure_port(port)
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":

    # parse args
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", default="all", help="Language to serve (or 'all')")
    parser.add_argument(
        "--conf",
        "--config",
        default="./config/deploy.yaml",
        help="Path to LibreASR configuration file",
    )
    args = parser.parse_args()
    lang = args.lang.lower()
    logging.basicConfig()

    # load config
    conf = load_config(args.conf, None if lang == "all" else lang)

    # spawn one process for each language
    #  or just the desired one
    if args.lang.lower() == "all":
        ps = []
        for l in conf["overrides"]["languages"]:
            if conf["overrides"]["languages"][l].get("enable", False):
                p = Process(target=serve, args=(args.conf, l))
                p.start()
                ps.append(p)
        for p in ps:
            p.join()
    else:
        serve(args.conf, lang)
