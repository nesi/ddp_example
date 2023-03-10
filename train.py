import os
import argparse

import torch
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from torch.utils.data.distributed import DistributedSampler
from torch.nn.parallel import DistributedDataParallel
from torch.distributed import init_process_group, destroy_process_group
from torch.distributed.elastic.multiprocessing.errors import record


class MyTrainDataset(Dataset):
    def __init__(self, size):
        self.size = size
        self.data = [(torch.rand(20), torch.rand(1)) for _ in range(size)]

    def __len__(self):
        return self.size

    def __getitem__(self, index):
        return self.data[index]


class Trainer:
    def __init__(
        self,
        model: torch.nn.Module,
        train_data: DataLoader,
        optimizer: torch.optim.Optimizer,
        local_rank: int,
        rank: int,
        save_every: int,
    ):
        self.local_rank = local_rank
        self.rank = rank
        self.model = model.to(local_rank)
        self.train_data = train_data
        self.optimizer = optimizer
        self.save_every = save_every
        self.model = DistributedDataParallel(model, device_ids=[local_rank])

    def _run_batch(self, source, targets):
        self.optimizer.zero_grad()
        output = self.model(source)
        loss = F.cross_entropy(output, targets)
        loss.backward()
        self.optimizer.step()

    def _run_epoch(self, epoch):
        batch_size = len(next(iter(self.train_data))[0])
        if self.rank == 0:
            print(
                f"[GPU{self.rank}] Epoch {epoch} "
                f"| Batchsize: {batch_size} "
                f"| Steps: {len(self.train_data)}"
            )

        self.train_data.sampler.set_epoch(epoch)
        for source, targets in self.train_data:
            source = source.to(self.local_rank)
            targets = targets.to(self.local_rank)
            self._run_batch(source, targets)

    def _save_checkpoint(self, epoch):
        assert self.rank == 0, "this should not run on another rank than 0"
        ckp = self.model.module.state_dict()
        PATH = "checkpoint.pt"
        torch.save(ckp, PATH)
        print(f"Epoch {epoch} | Training checkpoint saved at {PATH}")

    def train(self, max_epochs: int):
        for epoch in range(max_epochs):
            self._run_epoch(epoch)
            if self.rank == 0 and epoch % self.save_every == 0:
                self._save_checkpoint(epoch)


def load_train_objs():
    train_set = MyTrainDataset(2048)
    model = torch.nn.Linear(20, 1)
    optimizer = torch.optim.SGD(model.parameters(), lr=1e-3)
    return train_set, model, optimizer


def prepare_dataloader(dataset: Dataset, batch_size: int):
    return DataLoader(
        dataset,
        batch_size=batch_size,
        pin_memory=True,
        shuffle=False,
        sampler=DistributedSampler(dataset),
    )


@record
def main():
    parser = argparse.ArgumentParser(description="simple distributed training job")
    parser.add_argument(
        "--total_epochs", default=10, type=int, help="Total epochs to train the model"
    )
    parser.add_argument(
        "--save_every", default=5, type=int, help="How often to save a snapshot"
    )
    parser.add_argument(
        "--batch_size",
        default=32,
        type=int,
        help="Input batch size on each device (default: 32)",
    )
    args = parser.parse_args()

    print(
        "### Worker info ###",
        f"node name: {os.environ.get('SLURMD_NODENAME', None)}",
        f"local rank: {os.environ['LOCAL_RANK']}",
        f"local world size: {os.environ['LOCAL_WORLD_SIZE']}",
        f"rank: {os.environ['RANK']}",
        f"world size: {os.environ['WORLD_SIZE']}",
        f"master address: {os.environ['MASTER_ADDR']}",
        f"master port: {os.environ['MASTER_PORT']}",
        sep="\n",
        flush=True,
    )

    init_process_group(backend="nccl")

    dataset, model, optimizer = load_train_objs()
    train_data = prepare_dataloader(dataset, args.batch_size)

    local_rank = int(os.environ["LOCAL_RANK"])
    rank = int(os.environ["RANK"])
    trainer = Trainer(model, train_data, optimizer, local_rank, rank, args.save_every)

    trainer.train(args.total_epochs)

    destroy_process_group()


if __name__ == "__main__":
    main()
