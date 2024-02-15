from pathlib import Path
from dacapo.blockwise.scheduler import run_blockwise
from dacapo.compute_context import ComputeContext, LocalTorch
from dacapo.experiments.datasplits.datasets.arrays.zarr_array import ZarrArray
from dacapo.store.array_store import LocalArrayIdentifier
from .argmax_post_processor_parameters import ArgmaxPostProcessorParameters
from .post_processor import PostProcessor
import numpy as np
from daisy import Roi, Coordinate


class ArgmaxPostProcessor(PostProcessor):
    def __init__(self):
        pass

    def enumerate_parameters(self):
        """Enumerate all possible parameters of this post-processor. Should
        return instances of ``PostProcessorParameters``."""

        yield ArgmaxPostProcessorParameters(id=1)

    def set_prediction(self, prediction_array_identifier):
        self.prediction_array = ZarrArray.open_from_array_identifier(
            prediction_array_identifier
        )

    def process(
        self,
        parameters,
        output_array_identifier,
        compute_context: ComputeContext | str = LocalTorch(),
        num_workers: int = 16,
        chunk_size: Coordinate = Coordinate((64, 64, 64)),
    ):
        output_array = ZarrArray.create_from_array_identifier(
            output_array_identifier,
            [dim for dim in self.prediction_array.axes if dim != "c"],
            self.prediction_array.roi,
            None,
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
        )
        return output_array
