#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
@author: Tiantian
"""
import pdb
import torch
import torch.nn as nn
from torch import Tensor
from torch.nn import functional as F
from torch.nn.utils.rnn import pack_padded_sequence
from torch.nn.utils.rnn import pad_packed_sequence
from typing import Dict
from typing import Iterable, Optional
import numpy as np


class audio_video_classifier(nn.Module):
    def __init__(self, num_classes, audio_input_dim, video_input_dim, hidden_size=128):
        super(audio_video_classifier, self).__init__()
        self.dropout_p = 0.25
        self.rnn_dropout = nn.Dropout(self.dropout_p)

        self.audio_rnn = nn.GRU(input_size=128, hidden_size=hidden_size, 
                                num_layers=1, batch_first=True, 
                                dropout=self.dropout_p, bidirectional=True)

        self.video_rnn = nn.GRU(input_size=video_input_dim, hidden_size=hidden_size, 
                                num_layers=1, batch_first=True, 
                                dropout=self.dropout_p, bidirectional=True)

        # conv module
        self.audio_conv = nn.Sequential(
            nn.Conv1d(audio_input_dim, 64, kernel_size=5, padding=2),
            nn.ReLU(),
            nn.MaxPool1d(kernel_size=2, stride=2),
            nn.Dropout(self.dropout_p),
            
            nn.Conv1d(64, 96, kernel_size=5, padding=2),
            nn.ReLU(),
            nn.MaxPool1d(kernel_size=2, stride=2),
            nn.Dropout(self.dropout_p),

            nn.Conv1d(96, 128, kernel_size=5, padding=2),
            nn.ReLU(),
            nn.MaxPool1d(kernel_size=2, stride=2),
            nn.Dropout(self.dropout_p),
        )

        self.bn = nn.BatchNorm1d(video_input_dim)
        self.bn1 = nn.BatchNorm1d(hidden_size*2)

        self.init_weight()

        # classifier head
        self.classifier = nn.Sequential(
            nn.Linear(256, 128),
            nn.ReLU(),
            nn.Linear(128, num_classes)
        )

        self.audio_proj = nn.Sequential(
            # nn.BatchNorm1d(hidden_size*2),
            nn.Linear(hidden_size*2, 128)
        )

        self.video_proj = nn.Sequential(
            # nn.BatchNorm1d(hidden_size*2),
            nn.Linear(hidden_size*2, 128)
        )


    def init_weight(self):
        for m in self._modules:
            if type(m) == nn.Linear:
                torch.nn.init.xavier_uniform(m.weight)
                m.bias.data.fill_(0.01)
            if type(m) == nn.Conv1d:
                torch.nn.init.xavier_uniform(m.weight)
                m.bias.data.fill_(0.01)

    def forward(self, x_audio, x_video):
        
        # audio
        x_audio = x_audio.float()
        x_audio = x_audio.permute(0, 2, 1)
        x_audio = self.audio_conv(x_audio)
        x_audio = x_audio.permute(0, 2, 1)
        
        x_audio, _ = self.audio_rnn(x_audio)
        # x_audio = torch.mean(x_audio, dim=1)
        x_audio = x_audio[:, 0, :]
        # x = self.bn(x)

        # video
        x_video = x_video.float()
        x_video = x_video.permute(0, 2, 1)
        # x_video = self.bn(x_video)
        x_video = x_video.permute(0, 2, 1)
        x_video, _ = self.video_rnn(x_video)
        # x_video = torch.mean(x_video, dim=1)
        x_video = x_video[:, 0, :]
        # pdb.set_trace()

        # projection
        x_audio = self.audio_proj(x_audio)
        x_video = self.video_proj(x_video)
        x_mm = torch.concat((x_audio, x_video), dim=1)

        preds = self.classifier(x_mm)
        return preds


class audio_text_classifier(nn.Module):
    def __init__(self, num_classes, audio_input_dim, text_input_dim, prosody_dim, hidden_size=64, att=None):
        super(audio_text_classifier, self).__init__()
        self.dropout_p = 0.25
        
        encoder_layer = nn.TransformerEncoderLayer(d_model=768, nhead=8, dim_feedforward=2048)
        self.text_transformer = nn.TransformerEncoder(encoder_layer, num_layers=1)
        self.audio_encoder = AudioEncoder(n_mels=80, n_ctx=250, n_state=512, n_head=8, n_layer=1)
        self.init_weight()

        # classifier head
        self.classifier = nn.Sequential(
            nn.Linear(256, 128),
            nn.ReLU(),
            nn.Dropout(self.dropout_p),
            nn.Linear(128, num_classes)
        )

        self.audio_proj = nn.Sequential(
            nn.Linear(512, 128)
        )

        self.text_proj = nn.Sequential(
            nn.Linear(768, 128)
        )


    def init_weight(self):
        for m in self._modules:
            if type(m) == nn.Linear:
                torch.nn.init.xavier_uniform(m.weight)
                m.bias.data.fill_(0.01)
            if type(m) == nn.Conv1d:
                torch.nn.init.xavier_uniform(m.weight)
                m.bias.data.fill_(0.01)

    def forward(self, x_audio, x_prosody, x_text):
        
        # audio
        x_audio = x_audio.float()
        x_audio = x_audio.permute(0, 2, 1)
        x_audio = self.audio_encoder(x_audio)
        # x_audio = x_audio[:, 0, :]
        x_audio = torch.mean(x_audio, dim=1)
        # pdb.set_trace()
        
        # video
        x_text = x_text.float()
        x_text = self.text_transformer(x_text)
        # x_text = x_text[:, 0, :]
        x_text = torch.mean(x_text, dim=1)
        
        # projection
        x_audio = self.audio_proj(x_audio)
        x_text = self.text_proj(x_text)
        x_mm = torch.concat((x_audio, x_text), dim=1)

        preds = self.classifier(x_mm)
        return preds


class LayerNorm(nn.LayerNorm):
    def forward(self, x: Tensor) -> Tensor:
        return super().forward(x.float()).type(x.dtype)


class Linear(nn.Linear):
    def forward(self, x: Tensor) -> Tensor:
        return F.linear(
            x, self.weight.to(x.dtype), None if self.bias is None else self.bias.to(x.dtype)
        )

class Conv1d(nn.Conv1d):
    def _conv_forward(self, x: Tensor, weight: Tensor, bias: Optional[Tensor]) -> Tensor:
        return super()._conv_forward(
            x, weight.to(x.dtype), None if bias is None else bias.to(x.dtype)
        )


def sinusoids(length, channels, max_timescale=10000):
    """Returns sinusoids for positional embedding"""
    assert channels % 2 == 0
    log_timescale_increment = np.log(max_timescale) / (channels // 2 - 1)
    inv_timescales = torch.exp(-log_timescale_increment * torch.arange(channels // 2))
    scaled_time = torch.arange(length)[:, np.newaxis] * inv_timescales[np.newaxis, :]
    return torch.cat([torch.sin(scaled_time), torch.cos(scaled_time)], dim=1)


class AudioEncoder(nn.Module):
    def __init__(self, n_mels: int, n_ctx: int, n_state: int, n_head: int, n_layer: int):
        super().__init__()
        self.conv1 = Conv1d(n_mels, n_state, kernel_size=3, padding=1)
        self.conv2 = Conv1d(n_state, n_state, kernel_size=3, stride=4, padding=1)
        self.register_buffer("positional_embedding", sinusoids(n_ctx, n_state))
        self.dropout = nn.Dropout(p=0.1)
        
        self.blocks: Iterable[ResidualAttentionBlock] = nn.ModuleList(
            [ResidualAttentionBlock(n_state, n_head) for _ in range(n_layer)]
        )
        self.ln_post = LayerNorm(n_state)

    def forward(self, x: Tensor):
        """
        x : torch.Tensor, shape = (batch_size, n_mels, n_ctx)
            the mel spectrogram of the audio
        """
        x = F.gelu(self.conv1(x))
        x = F.gelu(self.conv2(x))
        x = x.permute(0, 2, 1)
        # pdb.set_trace()
        assert x.shape[1:] == self.positional_embedding.shape, "incorrect audio shape"
        x = (x + self.positional_embedding).to(x.dtype)
        x = self.dropout(x)
        for block in self.blocks:
            x = block(x)

        x = self.ln_post(x)
        return x
    
    
class MultiHeadAttention(nn.Module):
    def __init__(self, n_state: int, n_head: int):
        super().__init__()
        self.n_head = n_head
        self.query = Linear(n_state, n_state)
        self.key = Linear(n_state, n_state, bias=False)
        self.value = Linear(n_state, n_state)
        self.out = Linear(n_state, n_state)

    def forward(
        self,
        x: Tensor,
        xa: Optional[Tensor] = None,
        mask: Optional[Tensor] = None,
        kv_cache: Optional[dict] = None,
    ):
        q = self.query(x)

        if kv_cache is None or xa is None or self.key not in kv_cache:
            # hooks, if installed (i.e. kv_cache is not None), will prepend the cached kv tensors;
            # otherwise, perform key/value projections for self- or cross-attention as usual.
            k = self.key(x if xa is None else xa)
            v = self.value(x if xa is None else xa)
        else:
            # for cross-attention, calculate keys and values once and reuse in subsequent calls.
            k = kv_cache[self.key]
            v = kv_cache[self.value]

        wv = self.qkv_attention(q, k, v, mask)
        return self.out(wv)

    def qkv_attention(self, q: Tensor, k: Tensor, v: Tensor, mask: Optional[Tensor] = None):
        n_batch, n_ctx, n_state = q.shape
        scale = (n_state // self.n_head) ** -0.25
        q = q.view(*q.shape[:2], self.n_head, -1).permute(0, 2, 1, 3) * scale
        k = k.view(*k.shape[:2], self.n_head, -1).permute(0, 2, 3, 1) * scale
        v = v.view(*v.shape[:2], self.n_head, -1).permute(0, 2, 1, 3)

        qk = q @ k
        if mask is not None:
            qk = qk + mask[:n_ctx, :n_ctx]

        w = F.softmax(qk.float(), dim=-1).to(q.dtype)
        return (w @ v).permute(0, 2, 1, 3).flatten(start_dim=2)


class ResidualAttentionBlock(nn.Module):
    def __init__(self, n_state: int, n_head: int, cross_attention: bool = False):
        super().__init__()

        self.attn = MultiHeadAttention(n_state, n_head)
        self.attn_ln = LayerNorm(n_state)

        self.cross_attn = MultiHeadAttention(n_state, n_head) if cross_attention else None
        self.cross_attn_ln = LayerNorm(n_state) if cross_attention else None

        n_mlp = n_state * 4
        self.mlp = nn.Sequential(Linear(n_state, n_mlp), nn.GELU(), Linear(n_mlp, n_state))
        self.mlp_ln = LayerNorm(n_state)

    def forward(
        self,
        x: Tensor,
        xa: Optional[Tensor] = None,
        mask: Optional[Tensor] = None,
        kv_cache: Optional[dict] = None,
    ):
        x = x + self.attn(self.attn_ln(x), mask=mask, kv_cache=kv_cache)
        if self.cross_attn:
            x = x + self.cross_attn(self.cross_attn_ln(x), xa, kv_cache=kv_cache)
        x = x + self.mlp(self.mlp_ln(x))
        return x
    
    
class PositionalEncoding(nn.Module):

    def __init__(self, d_model: int, dropout: float = 0.1, max_len: int = 5000):
        super().__init__()
        self.dropout = nn.Dropout(p=dropout)

        position = torch.arange(max_len).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2) * (-math.log(10000.0) / d_model))
        pe = torch.zeros(max_len, 1, d_model)
        pe[:, 0, 0::2] = torch.sin(position * div_term)
        pe[:, 0, 1::2] = torch.cos(position * div_term)
        self.register_buffer('pe', pe)

    def forward(self, x: Tensor) -> Tensor:
        """
        Args:
            x: Tensor, shape [seq_len, batch_size, embedding_dim]
        """
        x = x + self.pe[:x.size(0)]
        return self.dropout(x)
    