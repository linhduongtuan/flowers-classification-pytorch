import torch
import numpy as np
from torch import nn, optim
import torch.nn.functional as F
from torchvision import datasets, models, transforms
from torch.utils.data import DataLoader
from collections import OrderedDict
from PIL import Image
from torch import Tensor
import shutil
import argparse
import os

# device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

def validation(model, testloader, criterion, device):
    test_loss = 0
    accuracy = 0
    model.to(device)
    for images, labels in testloader:
        images, labels = images.to(device), labels.to(device)
        # images.resize_(images.shape[0], 3, 224, 224)

        output = model.forward(images)
        test_loss += criterion(output, labels).item()

        ps = torch.exp(output)
        equality = (labels.data == ps.max(dim=1)[1])
        accuracy += equality.type(torch.FloatTensor).mean()
    
    return test_loss, accuracy


def train(model, trainloader, validloader, epochs, print_every, criterion, optimizer, arch="vgg16", device='cuda', model_dir="models"):
    epochs = epochs
    print_every = print_every
    steps = 0
    
    # Change to train mode if not already
    model.train()
    # change to cuda
    model.to(device)

    best_accuracy = 0
    for e in range(epochs):
        running_loss = 0

        for (images, labels) in trainloader:
            steps += 1

            images, labels = images.to(device), labels.to(device)

            optimizer.zero_grad()

            # Forward and backward passes
            outputs = model.forward(images)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()

            running_loss += loss.item()

            if steps % print_every == 0:
                
                # Make sure network is in eval mode for inference
                model.eval()

                # Turn off gradients for validation, saves memory and computations
                with torch.no_grad():
                    validation_loss, accuracy = validation(model, validloader, criterion, device)

                print("Epoch: {}/{}.. ".format(e+1, epochs),
                      "Training Loss: {:.3f}.. ".format(running_loss/print_every),
                      "Validation Loss: {:.3f}.. ".format(validation_loss/len(validloader)),
                      "Validation Accuracy: {:.3f}".format((accuracy/len(validloader))*100))

                model.train()
                
                running_loss = 0
        
        is_best = accuracy > best_accuracy
        best_accuracy = max(accuracy, best_accuracy)
        save_checkpoint({
            'epoch': epochs,
            'classifier': model.classifier,
            'state_dict': model.state_dict(),
            'optimizer' : optimizer.state_dict(),
            'class_idx_mapping': model.class_idx_mapping,
            'arch': arch,
            'best_accuracy': (best_accuracy/len(validloader))*100
            }, is_best, model_dir, 'checkpoint.pth')

def save_checkpoint(state, is_best=False, model_dir="models", filename='checkpoint.pth'):
    torch.save(state, os.path.join(model_dir, filename))
    if is_best:
        shutil.copyfile(filename, os.path.join(model_dir,'model_best.pth'))


def check_accuracy_on_test(testloader, model):    
    correct = 0
    total = 0
    model.to('cuda')
    with torch.no_grad():
        for data in testloader:
            images, labels = data
            images, labels = images.to('cuda'), labels.to('cuda')
            outputs = model(images)
            _, predicted = torch.max(outputs.data, 1)
            total += labels.size(0)
            correct += (predicted == labels).sum().item()

    return 100 * correct / total


def load_data_folder(data_folder="data"):
    """
    Loads the dataset into a dataloader.

    Arguments:
        data_folder: Path to the folder where data resides. Should have two sub folders named "train" and "valid".

    Returns:
        train_dataloader: Train dataloader iterator.
        valid_dataloader: Validation dataloader iterator.
    """

    train_dir = os.path.join(data_folder, "train")
    valid_dir = os.path.join(data_folder, "valid")
    # Define transforms for the training, validation, and testing sets
    train_transforms = transforms.Compose([
        transforms.RandomRotation(30),
        transforms.RandomResizedCrop(size=224),
        transforms.RandomHorizontalFlip(),
        transforms.RandomVerticalFlip(),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ])

    validation_transforms = transforms.Compose([
        transforms.Resize(256),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ])

    # Load the datasets with ImageFolder
    train_dataset = datasets.ImageFolder(train_dir, transform=train_transforms)
    validation_dataset = datasets.ImageFolder(valid_dir, transform=validation_transforms)

    # Using the image datasets and the transforms, define the dataloaders
    train_dataloader = DataLoader(train_dataset, shuffle=True, batch_size=64, num_workers=4)
    valid_dataloader = DataLoader(validation_dataset, shuffle=True, batch_size=64, num_workers=4)

    return train_dataloader, valid_dataloader, train_dataset.class_to_idx

def build_model(arch="vgg16", hidden_units=4096, class_idx_mapping=None):
    my_local = dict()
    exec("model = models.{}(pretrained=True)".format(arch), globals(), my_local)

    model =  my_local['model']
    last_child = list(model.children())[-1]

    if type(last_child) == torch.nn.modules.linear.Linear:
        input_features = last_child.in_features
    elif type(last_child) == torch.nn.modules.container.Sequential:
        input_features = last_child[0].in_features

    for param in model.parameters():
        param.requires_grad = False

    classifier = nn.Sequential(OrderedDict([
                                            ('fc1', nn.Linear(input_features, hidden_units)),
                                            ('relu', nn.ReLU()),
                                            ('dropout', nn.Dropout(p=0.5)),
                                            ('fc2', nn.Linear(hidden_units, 102)),
                                            ('output', nn.LogSoftmax(dim=1))
                                            ]))
    
    model.classifier = classifier
    model.class_idx_mapping = class_idx_mapping

    return model

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir", help="Directory containing the dataset.",
                    default="data", nargs="?")

    VALID_ARCH_CHOICES = ("vgg16", "vgg13", "densenet121")
    ap.add_argument("--arch", help="Model architecture from 'torchvision.models'. (default: vgg16)", choices=VALID_ARCH_CHOICES,
                    default=VALID_ARCH_CHOICES[0])

    ap.add_argument("--hidden_units", help="Number of units the hidden layer should consist of. (default: 4096)",
                    default=4096, type=int)

    ap.add_argument("--learning_rate", help="Learning rate for Adam optimizer. (default: 0.001)",
                    default=0.001, type=float)

    ap.add_argument("--epochs", help="Number of iterations over the whole dataset. (default: 3)",
                    default=3, type=int)

    ap.add_argument("--gpu", help="Use GPU or CPU for training",
                    action="store_true")

    ap.add_argument("--model_dir", help="Directory which will contain the model checkpoints.",
                    default="models")
    args = vars(ap.parse_args())

    os.system("mkdir -p " + args["model_dir"])

    (train_dataloader, valid_dataloader, class_idx_mapping) = load_data_folder(data_folder=args["data_dir"])
    
    model = build_model(arch=args["arch"], hidden_units=args["hidden_units"], class_idx_mapping=class_idx_mapping)

    criterion = nn.NLLLoss()
    optimizer = optim.Adam(model.classifier.parameters(), lr=args["learning_rate"])

    device = None
    if args["gpu"]:
        device = "cuda"
    else:
        device = "cpu"

    train(model=model, 
        trainloader=train_dataloader, 
        validloader=valid_dataloader,
        epochs=args["epochs"], 
        print_every=20, 
        criterion=criterion,
        optimizer=optimizer,
        arch=args["arch"],
        device=device,
        model_dir=args["model_dir"])

if __name__ == '__main__':
    main()