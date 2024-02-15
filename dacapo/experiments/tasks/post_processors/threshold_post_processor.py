from pathlib import Path
from dacapo.blockwise.scheduler import run_blockwise
from dacapo.compute_context import ComputeContext, LocalTorch
from dacapo.experiments.datasplits.datasets.arrays.zarr_array import ZarrArray
from .threshold_post_processor_parameters import ThresholdPostProcessorParameters
from .post_processor import PostProcessor
import numpy as np
from daisy import Roi, Coordinate

from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from dacapo.store.local_array_store import LocalArrayIdentifier
    from dacapo.experiments.tasks.post_processors import (
        ThresholdPostProcessorParameters,
    )


class ThresholdPostProcessor(PostProcessor):
    def __init__(self):
        pass

    def enumerate_parameters(self) -> Iterable[ThresholdPostProcessorParameters]:
        """Enumerate all possible parameters of this post-processor."""
        for i, threshold in enumerate([-0.1, 0.0, 0.1]):
            yield ThresholdPostProcessorParameters(id=i, threshold=threshold)

    def set_prediction(self, prediction_array_identifier: "LocalArrayIdentifier"):
        self.prediction_array = ZarrArray.open_from_array_identifier(
            prediction_array_identifier
        )

    def process(
        self,
        parameters: "ThresholdPostProcessorParameters",
        output_array_identifier: "LocalArrayIdentifier",
        compute_context: ComputeContext | str = LocalTorch(),
        num_workers: int = 16,
        chunk_size: Coordinate = Coordinate((64, 64, 64)),
    ) -> ZarrArray:
        # TODO: Investigate Liskov substitution princple and whether it is a problem here
        # OOP theory states the super class should always be replaceable with its subclasses
        # meaning the input arguments to methods on the subclass can only be more loosely
        # constrained and the outputs can only be more highly constrained. In this case
        # we know our parameters will be a `ThresholdPostProcessorParameters` class,
        # which is more specific than the `PostProcessorParameters` parent class.
        # Seems unrelated to me since just because all `PostProcessors` use some
        # `PostProcessorParameters` doesn't mean they can use any `PostProcessorParameters`
        # so our subclasses aren't directly replaceable anyway.
        # Might be missing something since I only did a quick google, leaving this here
        # for me or someone else to investigate further in the future.
        output_array = ZarrArray.create_from_array_identifier(
            output_array_identifier,
            self.prediction_array.axes,
            self.prediction_array.roi,
            self.prediction_array.num_channels,
            self.prediction_array.voxel_size,
            np.uint8,
        )

        read_roi = Roi((0, 0, 0), self.prediction_array.voxel_size * chunk_size)
        # run blockwise prediction
        run_blockwise(
            worker_file=str(
                Path(Path(__file__).parent, "blockwise", "predict_worker.py")
            ),
            compute_context=compute_context,
            total_roi=self.prediction_array.roi,
            read_roi=read_roi,
            write_roi=read_roi,
            num_workers=num_workers,
            max_retries=2,  # TODO: make this an option
            timeout=None,  # TODO: make this an option
            ######
            input_array_identifier=LocalArrayIdentifier(
                self.prediction_array.file_name, self.prediction_array.dataset
            ),
            output_array_identifier=output_array_identifier,
            threshold=parameters.threshold,
        )

        return output_array
