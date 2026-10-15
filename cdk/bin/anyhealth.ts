#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { AnyHealthStack } from '../lib/anyhealth-stack';
import { loadDeployInputs, stageContentForLambda } from '../lib/config';

const app = new cdk.App();

// Stage content/*.md into the Lambda asset so it ships with every function.
stageContentForLambda();

const inputs = loadDeployInputs(app);

new AnyHealthStack(app, `${inputs.prefix}-rcs-demo`, {
  inputs,
  // Account from deployer credentials; region from agent.json or -c region
  // (never inherited from ambient config — loadDeployInputs throws without it).
  env: {
    account: inputs.account,
    region: inputs.region,
  },
  description: `${inputs.brandName} RCS messaging demo (AWS End User Messaging).`,
});

app.synth();
