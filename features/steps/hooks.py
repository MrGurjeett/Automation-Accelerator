"""
Hooks for pytest-bdd
"""
import logging
from pytest_bdd import given, when, then

logger = logging.getLogger(__name__)


def before_scenario(context):
    """Run before each scenario"""
    logger.info("Starting scenario")


def after_scenario(context):
    """Run after each scenario"""
    logger.info("Scenario completed")


def before_feature(context):
    """Run before each feature"""
    logger.info("Starting feature")


def after_feature(context):
    """Run after each feature"""
    logger.info("Feature completed")
