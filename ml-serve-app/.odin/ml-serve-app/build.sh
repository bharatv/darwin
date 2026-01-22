#!/usr/bin/env bash

mkdir -p ./target/ml-serve-app

cp -rf ./app_layer ./target/ml-serve-app/app_layer
cp -rf ./core ./target/ml-serve-app/core
cp -rf ./model ./target/ml-serve-app/model
