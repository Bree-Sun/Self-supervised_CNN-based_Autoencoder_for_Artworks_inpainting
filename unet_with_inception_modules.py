# -*- coding: utf-8 -*-
"""UNet_with_inception_modules.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1qP6fqbBCO1n0Y-3ppL0XrqGpgVkCwVvs
"""

import os
import gc
import PIL
import tqdm
import torch
import random
import shutil
import torchvision
import numpy as np
from torch import nn
import matplotlib.pyplot as plt
from torchsummary import summary
from torchvision import datasets, transforms
from torch.utils.data import Dataset, DataLoader
from sklearn.model_selection import train_test_split

# Unified Configuration Dictionary to change all the configurations in the code

CONFIG = {'model_type':'Vanilla_UNet_big_bce',
          'epochs':30,
          'lr':5e-4,
          'weight_decay':1e-5,
          'batch_size_train':64,
          'batch_size_eval':64,
          'coding_layer_activation':nn.Sigmoid,
          'kl_weights':0.01,
          'inception_out_multiplier':1.2, #times input channels count to get output channel count as inception module output
          'loss':nn.MSELoss(),
          'device':"cuda" if torch.cuda.is_available() else 'cpu'}

# seed everything for reproducibility 
def seed_everything(seed=42):
  random.seed(seed)
  os.environ['PYTHONHASHSEED'] = str(seed)
  np.random.seed(seed)
  torch.manual_seed(seed)
  torch.backends.cudnn.deterministic = True
  torch.backends.cudnn.benchmark = False

seed_everything()

def print_shape(verbose, to_print):
  if verbose:
    print(to_print)

def double_conv_layers(in_channels, out_channels, kernel_size, activation, padding='same', batch_norm=True, coding_layer=False):
  '''
  Return Double Convolutional layers given the input parameters

  in_channels: input channels for the first convolutional layer
  out_channels: output channels for the second convolutional layer
  kernel_size: kernel size to use for both the layers
  activation: activaiton to apply to both the layers, should pass a activation function and not string.
  padding: padding to be applied to the inputs, by default no padding.
  batch_norm: if True applies nn.BatchNorm2d() after every Convolutional layer.
  '''

  if batch_norm:
    double_conv = nn.Sequential(
                                nn.Conv2d(in_channels, out_channels, kernel_size, padding=padding),
                                nn.BatchNorm2d(out_channels),
                                activation(inplace=True),
                                nn.Conv2d(out_channels, out_channels, kernel_size, padding=padding),
                                nn.BatchNorm2d(out_channels),
                                activation(inplace=True) if not coding_layer else CONFIG['coding_layer_activation']())
  else:
    double_conv = nn.Sequential(
                                nn.Conv2d(out_channels, out_channels, kernel_size, padding=padding),
                                activation(inplace=True),
                                nn.Conv2d(out_channels, out_channels, kernel_size, padding=padding),
                                activation(inplace=True) if not coding_layer else CONFIG['coding_layer_activation']())
  
  return double_conv


class InceptionModule(nn.Module):
  '''
  Create a layer of Inception Module which were introduced in GoogLeNet, it is termed as "Convolutional layer on Steroids" by Aurelian geron in his book
  'Hands on ml with scikit learn and tensorflow'
  '''
  def __init__(self, input_channels, ratios={'c1':0.3, 'c2':0.35, 'c3':0.1, 'c4':0.25}, verbose=False, coding_layer=False):
    super().__init__()
    
    self.verbose = verbose
    self.ratios = ratios
    self.coding_layer = coding_layer

    self.inception_out = int(CONFIG['inception_out_multiplier']*input_channels)

    c1_in = int(self.ratios['c1']*input_channels)
    c1_out = c1_in

    c2_in = int(self.ratios['c2']*input_channels)
    c2_out = int(self.ratios['c2']*self.inception_out)

    c3_in = int(self.ratios['c3']*input_channels)
    c3_out = int(self.ratios['c3']*self.inception_out)

    c4_in = int(self.ratios['c4']*input_channels)
    c4_out = c4_in

    total_in = c1_in + c2_in + c3_in + c4_in

    if total_in != input_channels:
      c4_out += (input_channels-total_in) # decrease/increase the difference from last channel

    total_out = c1_out + c2_out + c3_out +c4_out

    if total_out != self.inception_out:
      c3_out += (self.inception_out - total_out) 

    

    self.channel_1 = nn.Conv2d(in_channels=input_channels, out_channels=c1_out, kernel_size=1, stride=1, padding='same')

    self.channel_2 = nn.Sequential(nn.Conv2d(in_channels=input_channels, out_channels=c2_in, kernel_size=1, stride=1, padding='same'),
                              nn.Conv2d(in_channels=c2_in, out_channels=c2_out, kernel_size=3, stride=1, padding='same'))
    
    self.channel_3 = nn.Sequential(nn.Conv2d(in_channels=input_channels, out_channels=c3_in, kernel_size=1, stride=1, padding='same'),
                              nn.Conv2d(in_channels=c3_in, out_channels=c3_out, kernel_size=5, stride=1, padding='same'))
    
    self.channel_4 = nn.Sequential(nn.MaxPool2d(kernel_size=3, stride=1, padding=1),
                              nn.Conv2d(in_channels=input_channels, out_channels=c4_out, kernel_size=1, stride=1, padding='same'))
    
  def forward(self, input):
    print_shape(self.verbose, f'input shape : {input.shape}')
    x1 = self.channel_1(input)
    print_shape(self.verbose, f'Channel 1 : {x1.shape}')
    x2 = self.channel_2(input)
    print_shape(self.verbose, f'Channel 2 : {x2.shape}')
    x3 = self.channel_3(input)
    print_shape(self.verbose, f'Channel 3 : {x3.shape}')
    x4 = self.channel_4(input)
    print_shape(self.verbose, f'Channel 4 : {x4.shape}')
    x = CONFIG['coding_layer_activation']()(torch.cat([x1, x2, x3, x4], 1)) if self.coding_layer else torch.cat([x1, x2, x3, x4], 1)
    print_shape(self.verbose, f'Final shape : {x.shape}')
    return x

class UNet(nn.Module):
  def __init__(self, 
               down_conv_out=[64, 128, 256, 512], 
               down_conv_ks=[3, 3, 3, 3],
               down_conv_activation=nn.ReLU,
               up_conv_out=[256, 128, 64],
               up_conv_ks=[3, 3, 3],
               up_conv_activation=nn.ReLU,
               pad='same',
               add_inception=False,
               sparse_encoder=False,
               verbose=False):
    super().__init__()
    

    self.down_conv_out = down_conv_out
    self.down_conv_ks = down_conv_ks
    self.down_conv_activation = down_conv_activation
    self.up_conv_out = up_conv_out
    self.up_conv_ks = up_conv_ks
    self.up_conv_activation = up_conv_activation
    self.pad = pad 
    self.add_inception = add_inception # add inception module or not
    self.sparse_encoder = sparse_encoder # add sparsity using KL divergence on encoding layer to create a sparse autoencoder
    self.verbose = verbose # False if do not want shape transformations

    # Down Conv Layers
    self.down_conv1 = double_conv_layers(3, down_conv_out[0], down_conv_ks[0], down_conv_activation, padding=pad)
    self.down_conv2 = double_conv_layers(down_conv_out[0], down_conv_out[1], down_conv_ks[1], down_conv_activation, padding=pad)
    self.down_conv3 = double_conv_layers(down_conv_out[1], down_conv_out[2], down_conv_ks[2], down_conv_activation, padding=pad)
    self.down_conv4 = double_conv_layers(down_conv_out[2], down_conv_out[3], down_conv_ks[3], down_conv_activation, padding=pad, coding_layer=not self.add_inception)

    # Inception Modules
    inception_in_1 = down_conv_out[3]
    inception_in_2 = int(CONFIG['inception_out_multiplier'] * inception_in_1)
    inception_in_3 = int(CONFIG['inception_out_multiplier'] * inception_in_2)
    self.inception_module_1 = InceptionModule(inception_in_1)
    self.inception_module_2 = InceptionModule(inception_in_2)
    self.inception_module_3 = InceptionModule(inception_in_3, coding_layer=True)
    
    # Conv Transpose layers
    transpose1_in = int(CONFIG['inception_out_multiplier'] * inception_in_3)
    self.up_transpose1 = nn.ConvTranspose2d(transpose1_in, up_conv_out[0], 2, 2) if self.add_inception else nn.ConvTranspose2d(down_conv_out[3], up_conv_out[0], 2, 2)
    self.up_transpose2 = nn.ConvTranspose2d(up_conv_out[0], up_conv_out[1], 2, 2)
    self.up_transpose3 = nn.ConvTranspose2d(up_conv_out[1], up_conv_out[2], 2, 2)
    
    # Up Conv Layers
    self.up_conv1 = double_conv_layers(down_conv_out[3], up_conv_out[0], up_conv_ks[0], up_conv_activation, padding=pad)
    self.up_conv2 = double_conv_layers(up_conv_out[0], up_conv_out[1], up_conv_ks[1], up_conv_activation, padding=pad)
    self.up_conv3 = double_conv_layers(up_conv_out[1], up_conv_out[2], up_conv_ks[2], up_conv_activation, padding=pad)

    # final output conv
    self.output_conv = nn.Conv2d(up_conv_out[2], 3, 1)

    # Maxpooling
    self.maxpool = nn.MaxPool2d(kernel_size=2, stride=2)


  def forward(self, input):

    # Down Conv Encoder Part
    print_shape(self.verbose, f'Start : {input.shape}')

    x1 = self.down_conv1(input)
    print_shape(self.verbose, f'After Down Conv 1 : {x1.shape}')

    x = self.maxpool(x1)
    print_shape(self.verbose, f'After maxpool : {x.shape}')

    x2 = self.down_conv2(x)
    print_shape(self.verbose, f'After Down Conv 2 : {x2.shape}')

    x = self.maxpool(x2)
    print_shape(self.verbose, f'After maxpool : {x.shape}')

    x3 = self.down_conv3(x)
    print_shape(self.verbose, f'After Down Conv 3 : {x3.shape}')

    x = self.maxpool(x3)
    print_shape(self.verbose, f'After maxpool : {x.shape}')

    encoding = self.down_conv4(x)                  # final encoder output to which we will apply loss for sparsity incase of sparse encoder
    print_shape(self.verbose, f'After Down Conv 4 : {encoding.shape}')

    if self.add_inception:
      x = self.inception_module_1(encoding)
      print_shape(self.verbose, f'After 1st Inception module : {x.shape}')

      x = self.inception_module_2(x)
      print_shape(self.verbose, f'After 2nd Inception module : {x.shape}')

      encoding = self.inception_module_3(x)
      print_shape(self.verbose, f'After 3rd Inception module : {encoding.shape}')

    # Up Conv Decoder Part
    x = self.up_transpose1(encoding) 
    print_shape(self.verbose, f'After Up Transpose 1 : {x.shape}')

    x = self.up_conv1(torch.cat([x, x3], 1)) # skip connection from down_conv3
    print_shape(self.verbose, f'After Up Conv 1 : {x.shape}')

    x = self.up_transpose2(x)
    print_shape(self.verbose, f'After Up Transpose 2 : {x.shape}')

    x = self.up_conv2(torch.cat([x, x2], 1)) # skip connection from down_conv2
    print_shape(self.verbose, f'After Up Conv 2 : {x.shape}')

    x = self.up_transpose3(x)
    print_shape(self.verbose, f'After Up Transpose 3 : {x.shape}')

    x = self.up_conv3(torch.cat([x, x1], 1)) # skip connection from down_conv1
    print_shape(self.verbose, f'After Up Conv 3 : {x.shape}')

    # final output conv layer
    x = self.output_conv(x)
    print_shape(self.verbose, f'After Final output conv : {x.shape}')
    
    if self.sparse_encoder:
      return x, encoding

    else:
      return x

# inception module test
image = torch.zeros(1, 512, 64, 64)
im = InceptionModule(512, verbose=True)
i = im(image)

# with inception modules
image = torch.zeros(1, 3, 128, 128)
model = UNet(add_inception=True, verbose=True)
x = model(image)









