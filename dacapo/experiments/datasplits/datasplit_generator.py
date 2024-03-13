from dacapo.experiments.tasks import TaskConfig
from pathlib import Path
from typing import List
from enum import Enum, EnumMeta
from funlib.geometry import Coordinate
from typing import Union

import zarr
from dacapo.experiments.datasplits.datasets.arrays import (
    ZarrArrayConfig,
    ZarrArray,
    ResampledArrayConfig,
    BinarizeArrayConfig,
    IntensitiesArrayConfig,
)
from dacapo.experiments.datasplits import TrainValidateDataSplitConfig
from dacapo.experiments.datasplits.datasets import RawGTDatasetConfig
import logging

logger = logging.getLogger(__name__)


def is_zarr_group(file_name: str, dataset: str):
    zarr_file = zarr.open(str(file_name))
    return isinstance(zarr_file[dataset], zarr.hierarchy.Group)


def resize_if_needed(
    array_config: ZarrArrayConfig, target_resolution: Coordinate, extra_str=""
):
    zarr_array = ZarrArray(array_config)
    raw_voxel_size = zarr_array.voxel_size

    raw_upsample = raw_voxel_size / target_resolution
    raw_downsample = target_resolution / raw_voxel_size
    if any([u > 1 or d > 1 for u, d in zip(raw_upsample, raw_downsample)]):
        return ResampledArrayConfig(
            name=f"{array_config.name}_resampled",
            source_array_config=array_config,
            upsample=raw_upsample,
            downsample=raw_downsample,
            interp_order=False,
        )
    else:
        return array_config


def get_right_resolution_array_config(
    container, dataset, target_resolution, extra_str=""
):
    level = 0
    current_dataset_path = Path(dataset, f"s{level}")
    if not (container / current_dataset_path).exists():
        raise FileNotFoundError(
            f"Path {container} is a Zarr Group and /s0 does not exist."
        )

    zarr_config = ZarrArrayConfig(
        name=f"{extra_str}_{dataset}_uint8",
        file_name=container,
        dataset=str(current_dataset_path),
        snap_to_grid=target_resolution,
    )
    zarr_array = ZarrArray(zarr_config)
    while (
        sum(zarr_array.voxel_size) <= sum(target_resolution / 2)
        and Path(container, Path(dataset, f"s{level+1}")).exists()
    ):
        level += 1
        zarr_config = ZarrArrayConfig(
            name=f"{extra_str}_{dataset}_uint8",
            file_name=container,
            dataset=str(Path(dataset, f"s{level}")),
            snap_to_grid=target_resolution,
        )

        zarr_array = ZarrArray(zarr_config)
    return resize_if_needed(zarr_config, target_resolution, extra_str)


class CustomEnumMeta(EnumMeta):
    def __getitem__(self, item):
        if item not in self._member_names_:
            raise KeyError(
                f"{item} is not a valid option of {self.__name__}, the valid options are {self._member_names_}"
            )
        return super().__getitem__(item)


class DatasetType(Enum, metaclass=CustomEnumMeta):
    val = 1
    train = 2


class SegmentationType(Enum, metaclass=CustomEnumMeta):
    semantic = 1
    instance = 2


class DatasetSpec:
    def __init__(
        self,
        dataset_type: Union[str, DatasetType],
        raw_container: Union[str, Path],
        raw_dataset: str,
        gt_container: Union[str, Path],
        gt_dataset: str,
    ):

        if isinstance(dataset_type, str):
            dataset_type = DatasetType[dataset_type.lower()]

        if isinstance(raw_container, str):
            raw_container = Path(raw_container)

        if isinstance(gt_container, str):
            gt_container = Path(gt_container)

        self.dataset_type = dataset_type
        self.raw_container = raw_container
        self.raw_dataset = raw_dataset
        self.gt_container = gt_container
        self.gt_dataset = gt_dataset


def generate_dataspec_from_csv(csv_path: Path):
    datasets = []
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file {csv_path} does not exist.")
    with open(csv_path, "r") as f:
        for line in f:
            dataset_type, raw_container, raw_dataset, gt_container, gt_dataset = (
                line.strip().split(",")
            )
            datasets.append(
                DatasetSpec(
                    dataset_type=DatasetType[dataset_type.lower()],
                    raw_container=Path(raw_container),
                    raw_dataset=raw_dataset,
                    gt_container=Path(gt_container),
                    gt_dataset=gt_dataset,
                )
            )

    return datasets


class DataSplitGenerator:
    """Generates DataSplitConfig for a given task config and datasets.
    Currently only supports:
     - semantic segmentation.
     - one channel raw and one channel gt.
     - no resizing

    """

    def __init__(
        self,
        name: str,
        datasets: List[DatasetSpec],
        input_resolution: Coordinate,
        output_resolution: Coordinate,
        segmentation_type: Union[str, SegmentationType] = "semantic",
        max_gt_downsample=32,
        max_gt_upsample=4,
        max_raw_training_downsample=16,
        max_raw_training_upsample=2,
        max_raw_validation_downsample=8,
        max_raw_validation_upsample=2,
        min_training_volume_size=8_000,  # 20**3
        raw_min=0,
        raw_max=255,
    ):
        self.name = name
        self.datasets = datasets
        self.input_resolution = input_resolution
        self.output_resolution = output_resolution
        self.target_class_name = None

        if isinstance(segmentation_type, str):
            segmentation_type = SegmentationType[segmentation_type.lower()]

        self.segmentation_type = segmentation_type
        self.max_gt_downsample = max_gt_downsample
        self.max_gt_upsample = max_gt_upsample
        self.max_raw_training_downsample = max_raw_training_downsample
        self.max_raw_training_upsample = max_raw_training_upsample
        self.max_raw_validation_downsample = max_raw_validation_downsample
        self.max_raw_validation_upsample = max_raw_validation_upsample
        self.min_training_volume_size = min_training_volume_size
        self.raw_min = raw_min
        self.raw_max = raw_max

    @property
    def class_name(self):
        if self.target_class_name is None:
            raise ValueError("Class name not set yet.")
        return self.target_class_name

    def check_class_name(self, class_name):
        if self.target_class_name is None:
            self.target_class_name = class_name
        elif self.target_class_name != class_name:
            raise ValueError(
                f"Datasets are having different class names:  {class_name} does not match {self.target_class_name}"
            )

    def compute(self):
        if self.segmentation_type == SegmentationType.semantic:
            return self.__generate_semantic_seg_datasplit()
        else:
            raise NotImplementedError(
                f"{self.segmentation_type} segmentation not implemented yet!"
            )

    def __generate_semantic_seg_datasplit(self):
        train_dataset_configs = []
        validation_dataset_configs = []
        for dataset in self.datasets:
            raw_config, gt_config = self.__generate_semantic_seg_dataset_crop(dataset)
            if dataset.dataset_type == DatasetType.train:
                train_dataset_configs.append(
                    RawGTDatasetConfig(
                        name=f"{dataset}_{self.class_name}_{self.output_resolution[0]}nm",
                        raw_config=raw_config,
                        gt_config=gt_config,
                    )
                )
            else:
                validation_dataset_configs.append(
                    RawGTDatasetConfig(
                        name=f"{dataset}_{self.class_name}_{self.output_resolution[0]}nm",
                        raw_config=raw_config,
                        gt_config=gt_config,
                    )
                )
        return TrainValidateDataSplitConfig(
            name=f"{self.name}_{self.segmentation_type}_{self.class_name}_{self.output_resolution[0]}nm",
            train_configs=train_dataset_configs,
            validate_configs=validation_dataset_configs,
        )

    def __generate_semantic_seg_dataset_crop(self, dataset: DatasetSpec):
        raw_container = dataset.raw_container
        raw_dataset = dataset.raw_dataset
        gt_path = dataset.gt_container
        gt_dataset = dataset.gt_dataset

        current_class_name = Path(gt_dataset).stem
        self.check_class_name(current_class_name)

        if not (raw_container / raw_dataset).exists():
            raise FileNotFoundError(
                f"Raw path {raw_container/raw_dataset} does not exist."
            )

        if not (gt_path / gt_dataset).exists():
            raise FileNotFoundError(f"GT path {gt_path/gt_dataset} does not exist.")

        if is_zarr_group(str(raw_container), raw_dataset):
            raw_config = get_right_resolution_array_config(
                raw_container, raw_dataset, self.input_resolution, "raw"
            )
        else:
            raw_config = resize_if_needed(
                ZarrArrayConfig(
                    name=f"raw_{raw_dataset}_uint8",
                    file_name=raw_container,
                    dataset=raw_dataset,
                ),
                self.input_resolution,
                "raw",
            )
        raw_config = IntensitiesArrayConfig(
            name=f"raw_{raw_dataset}_uint8",
            source_array_config=raw_config,
            min=self.raw_min,
            max=self.raw_max,
        )

        if is_zarr_group(str(gt_path), gt_dataset):
            gt_config = get_right_resolution_array_config(
                gt_path, gt_dataset, self.output_resolution, "gt"
            )
        else:
            gt_config = resize_if_needed(
                ZarrArrayConfig(
                    name=f"gt_{gt_dataset}_uint8",
                    file_name=gt_path,
                    dataset=gt_dataset,
                ),
                self.output_resolution,
                "gt",
            )
        gt_config = BinarizeArrayConfig(
            f"{dataset}_{self.class_name}_{self.output_resolution[0]}nm_binarized",
            source_array_config=gt_config,
            groupings=[(self.class_name, [])],
        )
        return raw_config, gt_config

    def generate_csv(self, csv_path: Path):
        print(f"Writing dataspecs to {csv_path}")
        with open(csv_path, "w") as f:
            for dataset in self.datasets:
                f.write(
                    f"{dataset.dataset_type.name},{str(dataset.raw_container)},{dataset.raw_dataset},{str(dataset.gt_container)},{dataset.gt_dataset}\n"
                )

    @staticmethod
    def generate_from_csv(
        csv_path: Path,
        intput_resolution: Coordinate,
        output_resolution: Coordinate,
        **kwargs,
    ):
        return DataSplitGenerator(
            csv_path.stem,
            generate_dataspec_from_csv(csv_path),
            intput_resolution,
            output_resolution,
            **kwargs,
        )
