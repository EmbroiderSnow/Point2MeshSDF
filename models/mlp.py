import torch
import torch.nn as nn
import torch.nn.functional as F

from .encoder import FourierFeatureTransform

class MLP(nn.Module):
    def __init__(
        self,
        latent_size,
        dims,
        dropout=None,
        dropout_prob=0.0,
        norm_layers=(),
        latent_in=(),
        weight_norm=False,
        xyz_in_all=None,
        use_tanh=False,
        latent_dropout=False,
        softplus_beta = 1.0,
        use_position_encoding = False,
        fourier_mapping_size = 0,
        fourier_scale = 1.0,
    ):
        super(MLP, self).__init__()

        if use_position_encoding:
            self.position_encoder = FourierFeatureTransform(
                num_input_channels=3,
                mapping_size=fourier_mapping_size,
                scale=fourier_scale
            )
            encoded_xyz_dim = fourier_mapping_size * 2
            input_dim = latent_size + encoded_xyz_dim
        else:
            input_dim = latent_size + 3

        dims = [input_dim] + dims + [1]
        self.use_position_encoding = use_position_encoding
        self.num_layers = len(dims) 
        self.norm_layers = norm_layers
        self.latent_in = latent_in
        self.latent_dropout = latent_dropout
        if self.latent_dropout:
            self.lat_dp = nn.Dropout(0.2)

        self.xyz_in_all = xyz_in_all
        self.weight_norm = weight_norm

        for layer in range(0, self.num_layers - 1):
            if layer + 1 in latent_in:
                out_dim = dims[layer + 1] - latent_size
            else:
                out_dim = dims[layer + 1]
                if self.xyz_in_all and layer != self.num_layers - 2:
                    out_dim -= 3

            if weight_norm and layer in self.norm_layers:
                setattr(
                    self,
                    "lin" + str(layer),
                    nn.utils.weight_norm(nn.Linear(dims[layer], out_dim)),
                )
            else:
                setattr(self, "lin" + str(layer), nn.Linear(dims[layer], out_dim))

            if (
                (not weight_norm)
                and self.norm_layers is not None
                and layer in self.norm_layers
            ):
                setattr(self, "bn" + str(layer), nn.LayerNorm(out_dim))

        self.use_tanh = use_tanh
        if use_tanh:
            self.tanh = nn.Tanh()
        self.softplus = nn.Softplus(beta=softplus_beta)

        self.dropout_prob = dropout_prob
        self.dropout = dropout
        self.th = nn.Tanh()

    def forward(self, input):
        xyz = input[:, -3:]
        latent_vecs = input[:, :-3] if input.shape[1] > 3 else None

        if latent_vecs is not None and self.use_position_encoding:
            encoded_xyz = self.position_encoder(xyz)
            if self.latent_dropout:
                latent_vecs = F.dropout(latent_vecs, p=0.2, training=self.training)
            x = torch.cat([latent_vecs, encoded_xyz], 1)
            # Regard the concatenation of latent_vec and encoded_xyz as mlp input
            input = x
        else:
            x = input

        for layer in range(0, self.num_layers - 1):
            lin = getattr(self, "lin" + str(layer))
            if layer in self.latent_in:
                x = torch.cat([x, latent_vecs], 1)
            elif layer != 0 and self.xyz_in_all:                                
                x = torch.cat([x, xyz], 1)
            x = lin(x)
            # last layer Tanh
            if layer == self.num_layers - 2 and self.use_tanh:
                x = self.tanh(x)
            if layer < self.num_layers - 2:
                if (
                    self.norm_layers is not None
                    and layer in self.norm_layers
                    and not self.weight_norm
                ):
                    bn = getattr(self, "bn" + str(layer))
                    x = bn(x)
                x = self.softplus(x)
                if self.dropout is not None and layer in self.dropout:
                    x = F.dropout(x, p=self.dropout_prob, training=self.training)

        return x
