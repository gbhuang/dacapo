from ..fixtures import *

from dacapo.experiments import Run
from dacapo.store.create_store import create_config_store, create_weights_store
from dacapo import validate

import pytest
from pytest_lazyfixture import lazy_fixture

import logging

logging.basicConfig(level=logging.INFO)


@pytest.mark.parametrize(
    "run_config",
    [
        lazy_fixture("distance_run"),
        lazy_fixture("dummy_run"),
        lazy_fixture("onehot_run"),
    ],
)
def test_validate(
    options,
    run_config,
):
    # create a store

    store = create_config_store()
    weights_store = create_weights_store()

    # store the configs

    store.store_run_config(run_config)

    run_config = store.retrieve_run_config(run_config.name)
    run = Run(run_config)

    # -------------------------------------

    # validate

    # test validating iterations for which we know there are weights
    weights_store.store_weights(run, 0)
    validate(run_config.name, 0, num_workers=4)
    weights_store.store_weights(run, 1)
    validate(run_config.name, 1, num_workers=4)

    # test validating weights that don't exist
    with pytest.raises(FileNotFoundError):
        validate(run_config.name, 2, num_workers=4)
