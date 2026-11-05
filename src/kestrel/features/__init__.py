"""Feature layer: pure, causal ``DataFrame -> DataFrame`` functions with declared lookbacks."""

from kestrel.features.builder import FeatureBuilder, build_features
from kestrel.features.registry import FEATURES, FeatureSpec, parse_feature_name, register, resolve

__all__ = [
    "FEATURES",
    "FeatureBuilder",
    "FeatureSpec",
    "build_features",
    "parse_feature_name",
    "register",
    "resolve",
]
