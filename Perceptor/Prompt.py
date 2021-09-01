from pytti import *
from torch import nn
from torch.nn import functional as F
import re
from CLIP import clip
import pytti
from PIL import Image
from pytti.Image import RGBImage

def spherical_dist_loss(x, y):
  x = F.normalize(x, dim=-1)
  y = F.normalize(y, dim=-1)
  return (x - y).norm(dim=-1).div(2).arcsin().pow(2).mul(2)

class Prompt(nn.Module):
  def __init__(self, embeds, weight, stop, text, prompt_string):
    super().__init__()
    self.register_buffer('embeds',  embeds)
    self.register_buffer('weight', torch.as_tensor(weight))
    self.register_buffer('stop',   torch.as_tensor(stop))
    self.input_axes = ('n', 'c', 'i')
    self.prompt_string = prompt_string
    self.text = text

  def __repr__(self):
    return self.prompt_string

  def __str__(self):
    return self.text

  def forward(self, input):
    """
    input: (Tensor) input CLIP embedding
    returns the input's loss compared to the saved embedding
    """
    dists = spherical_dist_loss(input, self.embeds)
    dists = dists * self.weight.sign()
    dists = self.weight.abs() * replace_grad(dists, torch.maximum(dists, self.stop))
    return dists.mean()


class MultiClipPrompt(Prompt):
  """
  Compares CLIP embeddings (text or image) to saved embeddings for multiple CLIP models simultaneously
  based on VQGAN+CLIP system by Katherine Crowson (https://github.com/crowsonkb)
  embed:  (Tensor) CLIP embeddings
  text:   (string) text representation
  weight: (nonzero float) overall strength of prompt. Negative weights negate the prompt
  stop:   (float in [-1,1], sign(stop) == sign(weight)) minimum comparison distance in CLIP embedding space
          regardless of sign, lesser stop values make the optimizer greedier and greater stop values make the optimizer lazier
          sign must match weight, so stop is in [-1,0) if weight < 0, or stop is in [0,1) if weight > 0
  """
  def __init__(self, prompt_string, perceptors=None, device=DEVICE):
    tokens = re.split(':', prompt_string, 2)
    tokens = tokens + ['', '1', '-inf'][len(tokens):]
    text, weight, stop = tokens
    text   = text.strip()
    weight = float(weight.strip())
    stop   = float(stop.strip())
    if perceptors is None:
      perceptors = pytti.Perceptor.CLIP_PERCEPTORS
    embeds = cat_with_pad([p.encode_text(clip.tokenize(text).to(device)).float() for p in perceptors])
    super().__init__(embeds, weight, stop, text, prompt_string)

class MultiClipImagePrompt(Prompt):
  def __init__(self, embedder, prompt_string="IMAGE PROMPT", pil_image=None, device=DEVICE):
    tokens = re.split('(?<!^http)(?<!s):|:(?!//)', prompt_string, 2)
    tokens = tokens + ['', '1', '-inf'][len(tokens):]
    text, weight, stop = tokens
    text = text.strip()
    if pil_image is None:
      pil_image = Image.open(fetch(text)).convert("RGB")
    width, height = pil_image.size
    img = RGBImage(width, height)
    img.encode_image(pil_image)
    weight = float(weight.strip())
    stop   = float(stop.strip())
    embeds = embedder(img).detach()
    self.input_axes = ('n', 'c', 'i')
    embeds = format_input(embeds,embedder,self)
    super().__init__(embeds, weight, stop, text+" (semantic)", prompt_string)
