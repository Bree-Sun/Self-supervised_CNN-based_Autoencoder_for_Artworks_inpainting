# -*- coding: utf-8 -*-
"""training_code_simCLR_first_draft.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1kWRBgCuuth5tahB9RCXK_s4Fyyp-sPj2
"""

#getting the latent features the unet model extracted from images for calculating contrastive loss
def double_conv_layers(in_channels, out_channels, kernel_size, activation, padding=0, batch_norm=True):

  if batch_norm:
    double_conv = nn.Sequential(
                                nn.Conv2d(in_channels, out_channels, kernel_size, padding=padding),
                                nn.BatchNorm2d(out_channels),
                                activation(inplace=True),
                                nn.Conv2d(out_channels, out_channels, kernel_size, padding=padding),
                                nn.BatchNorm2d(out_channels),
                                activation(inplace=True))
  else:
    double_conv = nn.Sequential(
                                nn.Conv2d(out_channels, out_channels, kernel_size, padding=padding),
                                activation(inplace=True),
                                nn.Conv2d(out_channels, out_channels, kernel_size, padding=padding),
                                activation(inplace=True))
  
  return double_conv

class SimCLR(nn.Module): 
    def __init__(self):
        super().__init__()
        self.down_conv1 = double_conv_layers(3, 64, 3, nn.ReLU, padding=1)
        self.down_conv2 = double_conv_layers(64, 128, 3, nn.ReLU, padding=1)
        self.down_conv3 = double_conv_layers(128, 256, 3, nn.ReLU, padding=1)
        self.down_conv4 = double_conv_layers(256, 512, 3, nn.ReLU, padding=1)
        self.maxpool = nn.MaxPool2d(kernel_size=2, stride=2)
        
        self.projection = nn.Sequential(
            nn.Linear(512, 256),
            nn.ReLU(),
            nn.Linear(256, 256)
        )

    def forward(self, x, projection == True):
        x = torch.cat(x, dim=0)
        x = self.maxpool(self.down_conv1(x))
        x = self.maxpool(self.down_conv2(x))
        x = self.maxpool(self.down_conv3(x))
        x = self.down_conv4(x)
        proj = self.projection(x)
        if projection==True:
          return proj
        else:
          return x

class decoder(nn.Module):
    def __init__(self):
        super().__init__()

        # Conv Transpose layers
        self.up_transpose1 = nn.ConvTranspose2d(512, 256, 2, 2)
        self.up_transpose2 = nn.ConvTranspose2d(256, 128, 2, 2)
        self.up_transpose3 = nn.ConvTranspose2d(128, 64, 2, 2)
    
        # Up Conv Layers
        self.up_conv1 = double_conv_layers(512, 256, 3, nn.ReLU, padding=1)
        self.up_conv2 = double_conv_layers(256, 128, 3, nn.ReLU, padding=1)
        self.up_conv3 = double_conv_layers(128, 64, 3, nn.ReLU, padding=1)

        # final output conv
        self.output_conv = nn.Conv2d(64, 3, 1)
    def forward(self, x):
        # Up Conv Decoder Part
        x = self.up_transpose1(x4)
        x = self.up_conv1(torch.cat([x, x3], 1)) # skip connection from down_conv3
        x = self.up_transpose2(x)
        x = self.up_conv2(torch.cat([x, x2], 1)) # skip connection from down_conv2
        x = self.up_transpose3(x)
        x = self.up_conv3(torch.cat([x, x1], 1)) # skip connection from down_conv1
        # final output conv layer
        x = self.output_conv(x)

        return x

#device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

def infoNCE_loss(args, features):

    labels = torch.cat([torch.arange(args.batch_size) for i in range(args.n_views)], dim=0)
    labels = (labels.unsqueeze(0) == labels.unsqueeze(1)).float() 
    #labels = labels.to(self.args.device)

    features = F.normalize(features, dim=1)

    similarity_matrix = torch.matmul(features, features.T) 
    
    mask = torch.eye(labels.shape[0], dtype=torch.bool) #.to(args.device)
    # ~mask is the negative of the mask

    labels = labels[~mask].view(labels.shape[0], -1) 
    similarity_matrix = similarity_matrix[~mask].view(similarity_matrix.shape[0], -1) 

    # select and combine multiple positives
    positives = similarity_matrix[labels.bool()].view(labels.shape[0], -1) 

    # select only the negatives
    negatives = similarity_matrix[~labels.bool()].view(similarity_matrix.shape[0], -1) 

    logits = torch.cat([positives, negatives], dim=1) 
    labels = torch.zeros(logits.shape[0], dtype=torch.long) #.to(args.device)

    logits = logits / args.temp

    return logits, labels

#the data should be in the form of pairs (each with a different mask) of an image like 
#[[image_mask1, image_mask2],[image1_mask1, image2_mask2]....]
#function that takes one image and returns a masked pair ?
class AttrDict(dict):
    def __init__(self, *args, **kwargs):
        super(AttrDict, self).__init__(*args, **kwargs)
        self.__dict__ = self

def get_batch(x, batch_size):
    N = np.shape(x)[0]
    for i in range(0, N, batch_size):
        batch = x[i : i + batch_size, :, :, :]
        yield batch

def get_torch_vars(xs, gpu=False):

    xs = torch.from_numpy(xs).float()
    if gpu:
        xs = xs.cuda()

    return Variable(xs)

def train_simCLR(train, args, gen=None):

    npr.seed(args.seed)

    save_dir = "outputs/" + args.experiment_name

    if gen is None:
        Net = globals()[args.model]
        #gen = Net(args.kernel, args.num_filters)
        gen = Net()

    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(gen.parameters(), lr=args.learn_rate)

    # Create the outputs folder if not created already
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    print("Beginning training ...")
    if args.gpu:
        gen.cuda()
    start = time.time()

    for epoch in range(args.epochs):
       
        gen.train()  
        losses = []
        for i, imgs in enumerate(get_batch(train, args.batch_size)):
            imgs = get_torch_vars(imgs, args.gpu)
            proj = gen([view for view in imgs])
            logits, labels = infoNCE_loss(args, proj)
            loss = criterion(logits, labels)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            losses.append(loss.item())

        print(epoch, loss.cpu().detach())

    return gen

args = AttrDict()
args_dict = {
    "gpu": True,
    "valid": False,
    "checkpoint": "",
    "colours": "./data/colours/colour_kmeans24_cat7.npy",
    "model": "SimCLR",
    'learn_rate':0.001, 
    "batch_size": 64,
    "epochs": 50,
    "seed": 0,
    "plot": False,
    "experiment_name": "contrastive learning",
    "visualize": False,
    "downsize_input": False,
}
args.update(args_dict)
simCLR = train_simCLR(data, args)

#the input data here should be in the form of pairs of three with masked images AND the original image?
def train(train, args, simCLR, gen=None):

    npr.seed(args.seed)

    save_dir = "outputs/" + args.experiment_name

    if gen is None:
        Net = globals()[args.model]
        gen = Net()
        simCLR=simCLR()

    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam(gen.parameters(), lr=args.learn_rate)

    # Create the outputs folder if not created already
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    print("Beginning training ...")
    if args.gpu:
        gen.cuda()
    start = time.time()

    for epoch in range(args.epochs):
       
        gen.train()  
        losses = []
        for i, labels, imgs in enumerate(get_batch(train, args.batch_size)): #labels: original images
            img_1, img_2 = get_torch_vars(imgs, args.gpu)
            out_1 = gen(simCLR(img_1, projection==False))
            out_2 = gen(simCLR(img_2, projection==False))

            loss = (criterion(out_1, labels) + criterion(out_2, labels))/2
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            losses.append(loss.item())

        print(epoch, loss.cpu().detach())

    return gen

args = AttrDict()
args_dict = {
    "gpu": True,
    "valid": False,
    "checkpoint": "",
    "colours": "./data/colours/colour_kmeans24_cat7.npy",
    "model": "decoder",
    'learn_rate':0.001, 
    "batch_size": 64,
    "epochs": 50,
    "seed": 0,
    "plot": False,
    "experiment_name": "Images inpainting",
    "visualize": False,
    "downsize_input": False,
}
args.update(args_dict)
simCLR = train_simCLR(data, args)