import torch
import torch.nn as nn


def maybe_post_quantize(model, debug=True):
    name = model.__class__.__name__
    try:
        model = torch.quantization.quantize_dynamic(
            model, {torch.nn.LSTM, torch.nn.Linear}, dtype=torch.qint8
        )
        if debug:
            print(f"[quantization] post-quantizing {name} done.")
    except:
        if debug:
            print(
                f"[quantization] post-quantizing {name} failed. Might lead to degraded model performance."
            )
    return model


def quantize_rnnt(m, backend='qnnpack'):

    # prepare
    prev_backend = torch.backends.quantized.engine
    torch.backends.quantized.engine = backend
    m = m.cpu()
    lang, lm = m.lang, m.lm
    del m.lang
    del m.lm

    # quantize
    m = torch.quantization.quantize_dynamic(
        m,  # the original model
        {Encoder, Predictor, Joint}, # a set of layers to dynamically quantize
        dtype=torch.qint8)

    # post restore
    torch.backends.quantized.engine = prev_backend
    m.lang = lang
    m.lm = lm

    return m


def save_quantized(m):
    m = m.eval()
    lang = None
    if hasattr(m, "lang"):
        lang = m.lang
        del m.lang
    torch.save(m.encoder, "t-e.pth")
    torch.save(m.predictor, "t-p.pth")
    torch.save(m.joint, "t-j.pth")
    if lang is not None:
        m.lang = lang


def load_quantized(m, paths, lang):
    m = m.cpu()
    kwargs = {"map_location": "cpu"}

    # extract paths
    pe, pp, pj = paths

    # load
    m.encoder = torch.load(pe, **kwargs)
    m.predictor = torch.load(pp, **kwargs)
    m.joint = torch.load(pj, **kwargs)

    # patch class (to fix eval, train and to)
    m.post_quantize()

    # set to eval mode
    m = m.eval()

    # debug
    print("[quantization] load_quantized(...) done")

    return m
