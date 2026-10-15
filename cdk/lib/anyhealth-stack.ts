import * as path from 'path';
import { execSync } from 'child_process';
import {
  Stack,
  StackProps,
  Duration,
  RemovalPolicy,
  CustomResource,
  CfnOutput,
} from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as kms from 'aws-cdk-lib/aws-kms';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3n from 'aws-cdk-lib/aws-s3-notifications';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as subs from 'aws-cdk-lib/aws-sns-subscriptions';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { HttpApi, HttpMethod, CorsHttpMethod, CfnStage } from 'aws-cdk-lib/aws-apigatewayv2';
import { HttpLambdaIntegration } from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import { HttpLambdaAuthorizer, HttpLambdaResponseType } from 'aws-cdk-lib/aws-apigatewayv2-authorizers';
import { Provider } from 'aws-cdk-lib/custom-resources';
import { DeployInputs, LAMBDA_DIR, MEDIA_DIR, SECURE_DOCS_DIR } from './config';

export interface AnyHealthStackProps extends StackProps {
  inputs: DeployInputs;
}

/**
 * The Python version of every function and layer this stack owns. The Lambda
 * runtime, the `pip --python-version` tag the layers are built for, and the
 * layers' compatibleRuntimes have to agree: compiled wheels built for another
 * minor version (Pillow, pillow-heif) install and deploy cleanly and then fail
 * to import at invoke time. The helper functions aws-cdk-lib adds for
 * BucketDeployment, S3 notifications and auto-delete pick their own runtimes
 * and are not covered by this.
 */
const PY_RUNTIME = lambda.Runtime.PYTHON_3_14;
const PY_TAG = '3.14'; // PY_RUNTIME.name without the "python" prefix
if (PY_RUNTIME.name !== `python${PY_TAG}`) {
  throw new Error(`PY_RUNTIME (${PY_RUNTIME.name}) and PY_TAG (${PY_TAG}) must name the same Python version`);
}

/**
 * The backend version the dashboard status bar shows next to the frontend's, so
 * an operator can tell at a glance whether the browser and the deployed Lambdas
 * came from the same tree. Computed by scripts/version.mjs — shelled out to
 * rather than imported because that script is ESM and this project compiles to
 * CommonJS; running it as a CLI keeps one implementation of the scheme.
 *
 * Synthesis must never fail over a cosmetic string, so any problem (no node on
 * PATH, script deleted, no git history) degrades to 'unknown'.
 */
function backendVersion(): string {
  try {
    return execSync(`node ${path.join(__dirname, '..', '..', 'scripts', 'version.mjs')} backend`, {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim() || 'unknown';
  } catch {
    return 'unknown';
  }
}

export class AnyHealthStack extends Stack {
  constructor(scope: Construct, id: string, props: AnyHealthStackProps) {
    super(scope, id, props);
    const { inputs } = props;
    const prefix = inputs.prefix;

    // ── Data ────────────────────────────────────────────────────────────
    const tableKey = new kms.Key(this, 'TableKey', {
      description: `${prefix} demo — DynamoDB customer-managed key`,
      enableKeyRotation: true,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    const table = new dynamodb.Table(this, 'Table', {
      tableName: `${prefix}-demo`,
      partitionKey: { name: 'pk', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'sk', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: 'ttl',
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: tableKey,
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
      removalPolicy: RemovalPolicy.DESTROY,
    });
    table.addGlobalSecondaryIndex({
      indexName: 'gsi1',
      partitionKey: { name: 'gsi1pk', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'gsi1sk', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // ── Media bucket (RCS reads card/product images from here) ──────────
    // Separate logging bucket — a bucket cannot log to itself.
    const accessLogsBucket = new s3.Bucket(this, 'MediaAccessLogs', {
      bucketName: `${prefix}-demo-access-logs-${this.account}-${this.region}`,
      removalPolicy: RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      lifecycleRules: [{ expiration: Duration.days(90) }],
    });
    const bucket = new s3.Bucket(this, 'Media', {
      bucketName: `${prefix}-demo-${this.account}-${this.region}`,
      removalPolicy: RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      versioned: true,
      serverAccessLogsBucket: accessLogsBucket,
      serverAccessLogsPrefix: 'media-access-logs/',
      // The secure-upload webview (lambda/webviews/upload-insurance-card.html)
      // PUTs the file bytes directly from the browser to this bucket using a
      // presigned URL — a genuine cross-origin request from the RCS webview's
      // origin to S3's. Without a CORS rule, Safari/WebKit (RCS webviews are
      // in-app browser sessions) fails that PUT with a generic "Load failed"
      // and no further detail. allowedOrigins is '*' rather than the API's
      // origin because the presigned URL is scoped to one object key and
      // time-boxed (600s, see dashboard_handler.create_upload_url); it is not
      // single-use, so S3 accepts it repeatedly until it expires. The security
      // boundary is the signature, not the origin check.
      cors: [{
        allowedMethods: [s3.HttpMethods.PUT],
        allowedOrigins: ['*'],
        allowedHeaders: ['*'],
        maxAge: 3600,
      }],
    });
    // Inbound RCS media (member -> agent photos/files) lands under this prefix
    // in the same bucket. Declared here because the resource policy below has
    // to name it; the role that writes to it is created further down.
    const INBOUND_MEDIA_PREFIX = 'inbound';

    // Key prefixes for member-submitted images. They must match
    // lambda/common.py (UPLOAD_RAW_PREFIX, UPLOAD_CONVERTED_PREFIX) and
    // lambda/media_convert.py (_NATIVE_CONVERTED_PREFIX) exactly.
    const UPLOAD_RAW_PREFIX = 'raw-uploads';
    const UPLOAD_CONVERTED_PREFIX = 'converted-uploads';
    const NATIVE_CONVERTED_PREFIX = 'converted-inbound';
    // Where End User Messaging puts a photo the member sends: the agent is given
    // INBOUND_MEDIA_PREFIX as its key prefix (TwoWayMediaS3KeyPrefix below) and
    // the service adds rcs/ (lambda/media_convert.py, _NATIVE_RCS_PREFIX). Declared
    // here because the IAM grants and the upload notifications both name it.
    const NATIVE_RCS_MEDIA_PREFIX = `${INBOUND_MEDIA_PREFIX}/rcs`;

    // Retention for member-submitted images. Nothing else removes them: DynamoDB
    // TTL deletes only the rows that index them (UPLOAD# rows expire after one
    // day, common.new_upload; the conversation rows that reference native photos
    // after 30, common.TTL_CONVERSATION_DAYS), so without these rules the
    // objects would stay in the bucket indefinitely. A raw original also keeps
    // its EXIF block (GPS position, device model), which the converted JPEG does
    // not. The bucket is versioned, so each rule also purges noncurrent versions
    // a day after they appear; that is what permanently deletes an expired
    // object, because expiration alone only adds a delete marker. Every rule is
    // scoped to a single prefix: media/ and secure-docs/ hold the deployed
    // static assets and are deliberately not listed.
    const memberMediaRetention: { keyPrefix: string; days: number }[] = [
      { keyPrefix: UPLOAD_RAW_PREFIX, days: 7 },
      { keyPrefix: UPLOAD_CONVERTED_PREFIX, days: 7 },
      { keyPrefix: INBOUND_MEDIA_PREFIX, days: 30 },
      { keyPrefix: NATIVE_CONVERTED_PREFIX, days: 30 },
    ];
    for (const { keyPrefix, days } of memberMediaRetention) {
      bucket.addLifecycleRule({
        id: `expire-${keyPrefix}`,
        prefix: `${keyPrefix}/`,
        expiration: Duration.days(days),
        noncurrentVersionExpiration: Duration.days(1),
        abortIncompleteMultipartUploadAfter: Duration.days(1),
      });
    }

    // The EUM service fetches media objects when it sends them, so anything it
    // can GetObject on is a candidate for crossing the RCS/carrier network. Two
    // grants can authorize that read, and both are per-prefix rather than
    // bucket-wide:
    //
    //   1. This policy, for the service principal. It is the mechanism AWS's
    //      RCS file-message page describes (the bucket needs a policy that
    //      lets the service read).
    //   2. The channel adapter role's s3:GetObject statement further down. A
    //      send needed it: with an explicit Deny on s3:GetObject for the
    //      whole bucket attached to that role, an image card and a PDF file
    //      message both failed with ValidationException
    //      (RESOURCE_NOT_ACCESSIBLE), and a PDF file message sent after the
    //      Deny was removed succeeded.
    //      The bucket's server access log also shows that role's session, not
    //      the service principal, as the requester of the read behind each
    //      accepted media send in the delivered logs.
    //
    // The prefixes are the ones something actually hands to the service as a
    // FileUrl:
    //
    //   media/             card art and the generic PDFs the flows send
    //                      (common.resolve_media)
    //   inbound/rcs/       a photo the member sent, echoed back into the thread
    //                      (this policy names all of inbound/, which also holds
    //                      the service's setup object; the role's grant is the
    //                      tighter inbound/rcs/)
    //   converted-inbound/ its normalized JPEG (common.inbound_media_url)
    //
    // The point of the narrowing is the prefix that is *not* in either grant:
    // `secure-docs/` (deployed just below) holds the PHI-shaped sample
    // document. A FileMessage naming secure-docs/rx-patient-info.pdf and one
    // naming a member photo under converted-uploads/ were refused with
    // ValidationException (RESOURCE_NOT_ACCESSIBLE) in testing, while one naming
    // media/rx-medication-facts.pdf succeeded. The document reaches the member
    // only through the webview, over HTTPS, via a short-lived presigned URL
    // (dashboard_handler.get_secure_doc). Same reasoning excludes raw-uploads/
    // and converted-uploads/ — member-submitted documents, which nothing echoes
    // over RCS.
    //
    // One gap remains: the service reads with the calling role's permissions,
    // so any role that holds both sms-voice:SendRcsMessage and s3:GetObject on a
    // prefix could send it. The dashboard role does for secure-docs/ and
    // converted-uploads/ (the shared sms-voice grant below, and its presign
    // reads), but no dashboard code path sends a message. Dropping the send
    // actions from the dashboard role would close it.
    //
    // AWS documents an aws:SourceAccount condition on every grant to the
    // sms-voice.amazonaws.com service principal (file messages, two-way
    // messaging and inbound media), so that the service acts on this account's
    // behalf only (confused deputy prevention). The bucket policy statement and
    // the trust policies of the two roles below carry it. The SNS topic policy
    // further down does not, matching the AWS example for that option.
    const fromThisAccount = { StringEquals: { 'aws:SourceAccount': this.account } };
    bucket.addToResourcePolicy(
      new iam.PolicyStatement({
        principals: [new iam.ServicePrincipal('sms-voice.amazonaws.com')],
        actions: ['s3:GetObject'],
        resources: [
          bucket.arnForObjects('media/*'),
          bucket.arnForObjects(`${INBOUND_MEDIA_PREFIX}/*`),
          bucket.arnForObjects('converted-inbound/*'),
        ],
        conditions: fromThisAccount,
      })
    );
    new s3deploy.BucketDeployment(this, 'MediaDeploy', {
      sources: [s3deploy.Source.asset(MEDIA_DIR)],
      destinationBucket: bucket,
      destinationKeyPrefix: 'media',
    });
    // Documents meant to stay out of file messages. A separate
    // deployment (rather than another folder under media/) so the S3 key
    // prefix, and therefore what the bucket policy above and the channel
    // adapter's role permit, distinguishes them.
    new s3deploy.BucketDeployment(this, 'SecureDocsDeploy', {
      sources: [s3deploy.Source.asset(SECURE_DOCS_DIR)],
      destinationBucket: bucket,
      destinationKeyPrefix: 'secure-docs',
    });

    // Writing to INBOUND_MEDIA_PREFIX is granted separately: per AWS's
    // documented pattern ("Receiving inbound RCS media"), through a
    // role-level permission policy (not a
    // bucket resource policy) granting s3:PutObject only — the service
    // never needs to read/delete/list this bucket for inbound media.
    // https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-inbound-media.html
    const twoWayMediaRole = new iam.Role(this, 'TwoWayMediaRole', {
      // IAM is a global service, so role names are unique per *account*, not per
      // region — the region has to be part of the name or deploying this stack to
      // a second region in the same account fails at change-set validation with
      // "Resource of type 'AWS::IAM::Role' ... already exists". The buckets above
      // carry ${this.region} for the same reason.
      roleName: `${prefix}-demo-twoway-media-${this.region}`,
      assumedBy: new iam.ServicePrincipal('sms-voice.amazonaws.com', {
        conditions: fromThisAccount,
      }),
    });
    twoWayMediaRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ['s3:PutObject'],
        resources: [bucket.arnForObjects(`${INBOUND_MEDIA_PREFIX}/*`)],
      })
    );

    // ── Inbound SNS topic (RCS inbound + status events land here) ───────
    // AWS-managed SNS key: EUM/RCS service principals can decrypt with it
    // without needing custom key-policy grants, unlike a customer-managed key.
    const inbound = new sns.Topic(this, 'Inbound', {
      topicName: `${prefix}-demo-inbound`,
      masterKey: kms.Alias.fromAliasName(this, 'SnsManagedKey', 'alias/aws/sns'),
    });
    inbound.addToResourcePolicy(
      new iam.PolicyStatement({
        principals: [new iam.ServicePrincipal('sms-voice.amazonaws.com')],
        actions: ['sns:Publish'],
        resources: [inbound.topicArn],
      })
    );

    // Role EUM assumes to publish inbound messages to the topic (two-way).
    const twoWayRole = new iam.Role(this, 'TwoWayRole', {
      // Account-global name — see the note on TwoWayMediaRole above.
      roleName: `${prefix}-demo-twoway-${this.region}`,
      assumedBy: new iam.ServicePrincipal('sms-voice.amazonaws.com', {
        conditions: fromThisAccount,
      }),
    });
    inbound.grantPublish(twoWayRole);

    // Shared secret gating the API's sensitive routes: the writes (send/push/
    // reply/reset/etc) and the reads that return recipient data (testers,
    // conversations, latest media, spend limits). This is a lightweight demo
    // control, not a substitute for a real identity provider in a production
    // deployment — see README.
    const apiKeySecret = new secretsmanager.Secret(this, 'ApiKeySecret', {
      secretName: `${prefix}-demo-api-key`,
      generateSecretString: { passwordLength: 32, excludePunctuation: true },
      removalPolicy: RemovalPolicy.DESTROY,
    });

    // ── Lambda dependency layer (modern boto3 with SendRcsMessage + pyyaml) ──
    // Dockerless-first: build the layer with a local pip that pulls linux
    // wheels; fall back to Docker bundling only if local pip isn't usable.
    const layerDir = path.join(LAMBDA_DIR, 'layer');
    const depsLayer = new lambda.LayerVersion(this, 'DepsLayer', {
      code: lambda.Code.fromAsset(layerDir, {
        bundling: {
          image: PY_RUNTIME.bundlingImage,
          // CDK only passes `docker run --platform` when this is set. Without
          // it, an Apple Silicon or other arm64 host runs the arm64 bundling
          // image and pip resolves arm64 wheels, which import fine locally and
          // then fail on the x86_64 Lambda runtime with Runtime.ImportModuleError
          // — a failure that appears only at invoke time, long after a clean
          // deploy. The local path below already pins x86_64 platform tags; this
          // makes the Docker fallback agree with it.
          platform: 'linux/amd64',
          command: [
            'bash',
            '-c',
            'pip install -r requirements.txt --platform manylinux2014_x86_64 ' +
              `--implementation cp --python-version ${PY_TAG} --only-binary=:all: ` +
              '-t /asset-output/python',
          ],
          local: {
            tryBundle(outputDir: string): boolean {
              const py = process.env.PYTHON || 'python3';
              try {
                execSync(
                  `${py} -m pip install -r "${path.join(layerDir, 'requirements.txt')}" ` +
                    `--platform manylinux2014_x86_64 --implementation cp --python-version ${PY_TAG} ` +
                    `--only-binary=:all: --upgrade -t "${path.join(outputDir, 'python')}"`,
                  { stdio: 'ignore' }
                );
                return true;
              } catch {
                return false; // fall back to Docker
              }
            },
          },
        },
      }),
      compatibleRuntimes: [PY_RUNTIME],
      // Stated explicitly because the pip --platform tags above hardcode
      // x86_64. If anyone moves the functions to arm64, this mismatch is
      // what CloudFormation should reject, instead of the layer loading and
      // failing on import at invoke time.
      compatibleArchitectures: [lambda.Architecture.X86_64],
      description: 'Modern boto3 (SendRcsMessage) + PyYAML',
    });

    // Shared application code (channel adapter + dashboard). content/*.md is
    // staged into lambda/_content at synth so it ships inside this asset.
    const appCode = lambda.Code.fromAsset(LAMBDA_DIR, {
      exclude: ['layer', 'media_layer', 'custom_resources', '**/__pycache__'],
    });

    // ── Media conversion layer (Pillow + pillow-heif for HEIC support) ──
    // Separate from DepsLayer: Pillow with libheif bundled is tens of MB,
    // and only media_convert.py needs it — keeping it isolated means
    // channel_adapter/dashboard cold starts don't carry that weight.
    // pillow-heif ships prebuilt manylinux wheels that vendor libheif,
    // libde265 and x265 as shared libraries (pillow_heif.libs/), so this
    // installs via plain pip like DepsLayer — no system libraries or
    // Docker-only build step required.
    const mediaLayerDir = path.join(LAMBDA_DIR, 'media_layer');
    const mediaLayer = new lambda.LayerVersion(this, 'MediaLayer', {
      code: lambda.Code.fromAsset(mediaLayerDir, {
        bundling: {
          image: PY_RUNTIME.bundlingImage,
          // See DepsLayer above. This layer is the one that actually breaks:
          // Pillow and pillow-heif are compiled extensions, so an arm64 wheel
          // here means media_convert fails on every invoke with
          // Runtime.ImportModuleError on PIL or pillow_heif.
          platform: 'linux/amd64',
          command: [
            'bash',
            '-c',
            'pip install -r requirements.txt --platform manylinux_2_28_x86_64 ' +
              `--implementation cp --python-version ${PY_TAG} --only-binary=:all: ` +
              '-t /asset-output/python',
          ],
          local: {
            tryBundle(outputDir: string): boolean {
              const py = process.env.PYTHON || 'python3';
              try {
                // manylinux_2_28 (not manylinux2014, used by DepsLayer) — the
                // only platform tag pillow-heif's PyPI wheels publish.
                // Lambda's Python 3.14 runtime is Amazon Linux 2023 (glibc
                // 2.34), well above the glibc 2.28 floor this tag requires.
                execSync(
                  `${py} -m pip install -r "${path.join(mediaLayerDir, 'requirements.txt')}" ` +
                    `--platform manylinux_2_28_x86_64 --implementation cp --python-version ${PY_TAG} ` +
                    `--only-binary=:all: --upgrade -t "${path.join(outputDir, 'python')}"`,
                  { stdio: 'ignore' }
                );
                return true;
              } catch {
                return false;
              }
            },
          },
        },
      }),
      compatibleRuntimes: [PY_RUNTIME],
      // Stated explicitly because the pip --platform tags above hardcode
      // x86_64. If anyone moves the functions to arm64, this mismatch is
      // what CloudFormation should reject, instead of the layer loading and
      // failing on import at invoke time.
      compatibleArchitectures: [lambda.Architecture.X86_64],
      description: 'Pillow + pillow-heif for inbound-upload HEIC normalization',
    });

    const configSetName = `${prefix}-demo-events`;

    const commonEnv: Record<string, string> = {
      DYNAMODB_TABLE: table.tableName,
      S3_BUCKET: bucket.bucketName,
      S3_INBOUND_MEDIA_PREFIX: INBOUND_MEDIA_PREFIX,
      RCS_AGENT_ID: inputs.rcsAgentId,
      CONFIG_SET_NAME: configSetName,
      BEDROCK_MODEL_ID: inputs.bedrockModelId,
      BEDROCK_REGION: inputs.bedrockRegion,
      // Opt-in, via `-c smsFallbackNumber=+1…`. Present only when the deployer
      // supplied an SMS-capable origination identity, because common.send_rcs
      // keys off "is this variable set" to decide whether to attach a
      // FallbackConfiguration at all.
      ...(inputs.smsFallbackNumber ? { SMS_FALLBACK_NUMBER: inputs.smsFallbackNumber } : {}),
    };

    // ── Channel adapter (inbound routing + sends) ───────────────────────
    const channelAdapterLogGroup = new logs.LogGroup(this, 'ChannelAdapterLogGroup', {
      logGroupName: `/aws/lambda/${prefix}-channel-adapter`,
      retention: logs.RetentionDays.TWO_WEEKS,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    const channelAdapter = new lambda.Function(this, 'ChannelAdapter', {
      functionName: `${prefix}-channel-adapter`,
      runtime: PY_RUNTIME,
      architecture: lambda.Architecture.X86_64, // must match the layers' pinned wheels
      handler: 'channel_adapter.lambda_handler',
      code: appCode,
      layers: [depsLayer],
      timeout: Duration.seconds(60),
      memorySize: 512,
      environment: commonEnv,
      logGroup: channelAdapterLogGroup,
    });

    // ── Dashboard API (also serves webviews) ────────────────────────────
    const dashboardLogGroup = new logs.LogGroup(this, 'DashboardLogGroup', {
      logGroupName: `/aws/lambda/${prefix}-dashboard`,
      retention: logs.RetentionDays.TWO_WEEKS,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    const dashboard = new lambda.Function(this, 'Dashboard', {
      functionName: `${prefix}-dashboard`,
      runtime: PY_RUNTIME,
      architecture: lambda.Architecture.X86_64, // must match the layers' pinned wheels
      handler: 'dashboard_handler.handler',
      code: appCode,
      layers: [depsLayer],
      timeout: Duration.seconds(30),
      memorySize: 512,
      environment: {
        ...commonEnv,
        CHANNEL_ADAPTER_FN: channelAdapter.functionName,
        // Reported verbatim by GET /api/version. Only the dashboard needs it:
        // it is the one function the console talks to, and a per-function
        // version would imply the halves can drift, which they cannot — every
        // Lambda here is built from the same asset.
        APP_VERSION: backendVersion(),
        // Shown on the Settings tab (GET /api/agent-identity) so an operator who
        // works in more than one account can see which one the API they are
        // connected to runs in. Informational only: nothing authorizes or routes
        // on it, and only the dashboard needs it, so the functions that handle
        // member traffic and uploads do not get it.
        DEPLOY_ACCOUNT_ID: this.account,
      },
      logGroup: dashboardLogGroup,
    });

    // ARNs for least-privilege scoping below. Some sms-voice actions
    // (CreateVerifiedDestinationNumber, DescribeVerifiedDestinationNumbers) have
    // no resource-level permissions defined by the service — those must stay
    // scoped to '*', which is inherent to the action, not an over-broad grant.
    const rcsAgentArn = this.formatArn({
      service: 'sms-voice',
      resource: 'rcs-agent',
      resourceName: inputs.rcsAgentId,
    });
    const configSetArn = this.formatArn({
      service: 'sms-voice',
      resource: 'configuration-set',
      resourceName: configSetName,
    });
    // The RCS agent's opt-out list. A new agent uses the account's list named
    // "Default", and both readers pass that name
    // (dashboard_handler.opted_out_numbers, channel_adapter.OPT_OUT_LIST_NAME).
    // If you point the agent at another list with UpdateRcsAgent
    // --opt-out-list-name, the grant below and those two names have to follow.
    const optOutListArn = this.formatArn({
      service: 'sms-voice',
      resource: 'opt-out-list',
      resourceName: 'Default',
    });
    // Bedrock model access: grant both the inference-profile ARN and the
    // underlying foundation-model ARN, per AWS's documented two-statement
    // pattern for cross-region inference (CRIS) profiles:
    // https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-use.html
    //
    // inputs.bedrockModelId may be a plain model id (e.g. "anthropic.claude-...")
    // or a CRIS profile id prefixed with its routing scope (e.g.
    // "global.anthropic.claude-sonnet-4-6" or "eu.anthropic...."). The prefix
    // is CRIS routing syntax, not part of the model id, so it must be stripped
    // to build a valid foundation-model ARN. A CRIS profile can invoke the
    // model in any of its source regions (not just the deploy region), so the
    // foundation-model ARN uses a region wildcard.
    //
    // All six geography prefixes must be listed. Missing one leaves it in place,
    // producing arn:...:foundation-model/au.anthropic.claude-... — an ARN that
    // matches nothing, so the grant covers no model and the AI vignettes fail
    // with AccessDenied at runtime.
    const baseBedrockModelId = inputs.bedrockModelId.replace(
      /^(us|eu|apac|au|jp|global)\./,
      ''
    );
    const bedrockFoundationModelArn = `arn:${this.partition}:bedrock:*::foundation-model/${baseBedrockModelId}`;
    const bedrockInferenceProfileArn = `arn:${this.partition}:bedrock:${inputs.bedrockRegion}:${this.account}:inference-profile/${inputs.bedrockModelId}`;

    // Object ARNs per key prefix, for the S3 grants below. bucket.grantRead(),
    // grantPut() and grantReadWrite() are deliberately not used: they expand to
    // action wildcards (s3:GetObject*, s3:GetBucket*, s3:List*, s3:Abort*,
    // s3:DeleteObject*), and the read ones also name the bucket ARN itself, so
    // the listing actions apply bucket-wide even when a key pattern is given.
    // Most prefixes hold keys minted at runtime (phone hashes, uuids, message
    // ids), so a prefix wildcard is the narrowest scope IAM can express for
    // them. media/ and secure-docs/ hold fixed keys deployed from the repo; they
    // get a prefix too, so that adding a file there needs no IAM edit. This
    // narrows the sample's own function roles only: the role CDK creates for
    // the BucketDeployment helper keeps the library's bucket-wide read and write
    // grants on this bucket.
    const mediaObjects = bucket.arnForObjects('media/*');
    const nativeRcsObjects = bucket.arnForObjects(`${NATIVE_RCS_MEDIA_PREFIX}/*`);
    const nativeConvertedObjects = bucket.arnForObjects(`${NATIVE_CONVERTED_PREFIX}/*`);
    const rawUploadObjects = bucket.arnForObjects(`${UPLOAD_RAW_PREFIX}/*`);
    const convertedUploadObjects = bucket.arnForObjects(`${UPLOAD_CONVERTED_PREFIX}/*`);
    const secureDocObjects = bucket.arnForObjects('secure-docs/*');

    // Grants shared by both functions.
    for (const fn of [channelAdapter, dashboard]) {
      table.grantReadWriteData(fn);
      fn.addToRolePolicy(
        new iam.PolicyStatement({
          actions: ['sms-voice:SendRcsMessage', 'sms-voice:SendTextMessage', 'sms-voice:DescribeRcsAgents'],
          resources: [rcsAgentArn, configSetArn],
        })
      );
      // A per-message FallbackConfiguration sends from a *phone number*
      // resource as well as the agent, so the statement above is not enough
      // for it. The number is supplied in E.164, not as an id or ARN, so this
      // cannot be scoped tighter than the account's own phone numbers in this
      // Region — and it is added only when fallback was explicitly opted into.
      if (inputs.smsFallbackNumber) {
        fn.addToRolePolicy(
          new iam.PolicyStatement({
            actions: ['sms-voice:SendRcsMessage', 'sms-voice:SendTextMessage'],
            resources: [
              Stack.of(this).formatArn({
                service: 'sms-voice',
                resource: 'phone-number',
                resourceName: '*',
              }),
              Stack.of(this).formatArn({
                service: 'sms-voice',
                resource: 'sender-id',
                resourceName: '*',
              }),
            ],
          })
        );
      }
      fn.addToRolePolicy(
        new iam.PolicyStatement({
          // These actions do not support resource-level permissions, so '*' is
          // inherent to the action rather than an over-broad grant.
          // DescribeSpendLimits backs the dashboard's account-wide RCS
          // quota warning (GET /api/health) — see dashboard_handler.get_health.
          // The three Describe*Registration* actions back GET
          // /api/agent-identity, which reads the agent's *registered* brand —
          // display name, description and presigned URLs to the uploaded logo
          // and banner — so device previews show the identity a handset will
          // actually render instead of the content/brand.md placeholder. See
          // dashboard_handler.get_agent_identity.
          actions: [
            'sms-voice:CreateVerifiedDestinationNumber',
            'sms-voice:DescribeVerifiedDestinationNumbers',
            'sms-voice:DescribeSpendLimits',
            'sms-voice:DescribeRegistrationFieldValues',
            'sms-voice:DescribeRegistrationAttachments',
          ],
          resources: ['*'],
        })
      );
      // DescribeOptedOutNumbers DOES support resource-level permissions (the
      // opt-out list is a required resource type), so it is scoped to the one
      // list the agent uses rather than '*'. A recipient who texts STOP (or a
      // custom OPT_OUT keyword) lands on that list and the service then refuses
      // every send to them. Both functions read it: the dashboard for the
      // Recipients tab's opt-out column, and the channel adapter to recognize
      // an opted-out member before it spends a model call on their message.
      fn.addToRolePolicy(
        new iam.PolicyStatement({
          actions: ['sms-voice:DescribeOptedOutNumbers'],
          resources: [optOutListArn],
        })
      );
      // DeleteVerifiedDestinationNumber DOES support resource-level permissions,
      // so scope it to the verified-destination-number resource type rather
      // than '*'. The specific ids are minted at runtime and not known at
      // deploy time, hence the resource-name wildcard — but it is still bounded
      // to this account and Region's verified destination numbers.
      // Verified test devices are limited to 10 per agent (the AWS quotas page
      // lists this quota as not adjustable), so removing one is the only way to
      // add an eleventh — DELETE /api/testers/{phone}, see
      // dashboard_handler.delete_tester.
      fn.addToRolePolicy(
        new iam.PolicyStatement({
          actions: ['sms-voice:DeleteVerifiedDestinationNumber'],
          resources: [
            this.formatArn({
              service: 'sms-voice',
              resource: 'verified-destination-number',
              resourceName: '*',
            }),
          ],
        })
      );
      fn.addToRolePolicy(
        new iam.PolicyStatement({
          actions: ['bedrock:InvokeModel'],
          resources: [bedrockFoundationModelArn, bedrockInferenceProfileArn],
        })
      );
    }

    // ── S3 grants, per function ─────────────────────────────────────────
    //
    // Channel adapter. Its code makes no S3 call: it never creates an S3 client
    // and only hands s3:// FileUrls to SendRcsMessage. It keeps s3:GetObject on
    // the three prefixes a FileUrl can name because the service reads the object
    // for a send with the calling role's permissions: with an explicit Deny on
    // s3:GetObject for the whole bucket attached to this role, an image card and
    // a PDF file message both failed with ValidationException
    // (RESOURCE_NOT_ACCESSIBLE), and a PDF file message sent after the Deny
    // was removed succeeded. The bucket's server access log shows this role's
    // session as the requester of one HEAD and one GET for each accepted media
    // send. Those requests carry no source IP and no user agent, unlike the
    // Lambdas' own boto3 calls and the browsers using presigned URLs. The
    // bucket policy's service-principal statement stays in place alongside this
    // grant, as AWS's RCS file-message page describes. s3:GetObject also
    // authorizes HeadObject. raw-uploads/, converted-uploads/ and secure-docs/
    // are not readable by this role.
    channelAdapter.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'EumReadsSendableMedia',
        actions: ['s3:GetObject'],
        resources: [mediaObjects, nativeRcsObjects, nativeConvertedObjects],
      })
    );

    // Dashboard. Almost every S3 call here is a presigned URL, which carries the
    // permissions of the role that signed it, so the role itself must hold the
    // action behind each one:
    //   GetObject  /api/media (dashboard_handler._MEDIA_ALLOWED_PREFIXES: media/,
    //              inbound/rcs/, converted-inbound/, converted-uploads/), the
    //              Demo tab's latest-photo preview, the upload-status preview,
    //              and the secure document (secure-docs/, get_secure_doc).
    //   PutObject  the webview's direct-to-S3 upload, raw-uploads/ only
    //              (create_upload_url). Nothing presigns a GET for raw-uploads/,
    //              so the role cannot read the originals back.
    // Reset (_delete_resettable_media) lists the versions under the four
    // prefixes that hold member- or demo-generated data and deletes them by
    // version id, never in media/ or secure-docs/. Listing needs
    // s3:ListBucketVersions on the bucket (s3:prefix is a valid condition key
    // there). s3:ListBucket is left out: the code does no key listing. Per the
    // S3 docs, a missing key answers 403 rather than 404 when the signer lacks
    // s3:ListBucket, and a presigned GET for a missing key under an allowed
    // prefix did answer 403 AccessDenied on a deployed stack, so an expired
    // object shows AccessDenied.
    //
    // The role holds both s3:DeleteObjectVersion and s3:DeleteObject, on the
    // same four ARNs, so Reset works. The code itself only ever deletes by
    // version id. The extra action adds no resource string, and the role can
    // already delete every version there; all it gains is writing a delete
    // marker. POST /api/reset passed on two deployed stacks with both actions
    // held (delete markers were present on one of them); this sample did not
    // try either action alone.
    dashboard.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'PresignedGet',
        actions: ['s3:GetObject'],
        resources: [
          mediaObjects,
          nativeRcsObjects,
          nativeConvertedObjects,
          convertedUploadObjects,
          secureDocObjects,
        ],
      })
    );
    dashboard.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'PresignedPutWebviewUpload',
        actions: ['s3:PutObject'],
        resources: [rawUploadObjects],
      })
    );
    dashboard.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'ResetListVersions',
        actions: ['s3:ListBucketVersions'],
        resources: [bucket.bucketArn],
        conditions: {
          StringLike: {
            's3:prefix': [
              `${NATIVE_RCS_MEDIA_PREFIX}/*`,
              `${UPLOAD_RAW_PREFIX}/*`,
              `${UPLOAD_CONVERTED_PREFIX}/*`,
              `${NATIVE_CONVERTED_PREFIX}/*`,
            ],
          },
        },
      })
    );
    dashboard.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'ResetDeleteVersions',
        actions: ['s3:DeleteObjectVersion', 's3:DeleteObject'],
        resources: [nativeRcsObjects, rawUploadObjects, convertedUploadObjects, nativeConvertedObjects],
      })
    );

    // Keyword management is the dashboard's alone: the Settings tab's custom-
    // keyword panel (GET/POST/DELETE /api/keywords). The channel adapter never
    // lists, writes or deletes keywords (the service answers them, see
    // channel_adapter._screen_freetext), so it gets none of these.
    //
    // DescribeKeywords is a list/read and stays at '*' like the verified-
    // destination-number reads in the shared grants above.
    dashboard.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['sms-voice:DescribeKeywords'],
        resources: ['*'],
      })
    );
    // PutKeyword and DeleteKeyword DO support resource-level permissions, so
    // they are scoped to the one origination identity the dashboard passes:
    // the RCS agent. A keyword call made with an RCS agent id is authorized
    // against the agent's own ARN
    // (arn:<partition>:sms-voice:<region>:<account>:rcs-agent/<id>), so that is
    // the resource granted here; a role without it gets an
    // AccessDeniedException naming that ARN as the resource. This stack has no
    // phone number or pool to grant.
    dashboard.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['sms-voice:PutKeyword', 'sms-voice:DeleteKeyword'],
        resources: [rcsAgentArn],
      })
    );
    // EXPERIMENTAL — Chime SDK meetings for the WebRTC video visit. Dashboard
    // only: the channel adapter mints the visit token (a DynamoDB write) but
    // never touches Chime, because the meeting is created lazily on first join
    // so an unopened invitation costs nothing.
    //
    // Resource '*' on CreateMeeting is inherent: the meeting does not exist yet,
    // so there is no ARN to name. The other three DO support resource-level
    // permissions, so they are scoped to the Chime meeting resource type
    // (meeting/* in this account and Region) following the least-privilege
    // pattern AWS documents, rather than sharing CreateMeeting's '*'. The
    // meaningful runtime limits remain elsewhere: an expiring token, a
    // per-visit attendee cap, and DeleteMeeting on leave.
    dashboard.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['chime:CreateMeeting'],
        resources: ['*'],
      })
    );
    dashboard.addToRolePolicy(
      new iam.PolicyStatement({
        actions: [
          'chime:CreateAttendee',
          'chime:DeleteMeeting',
          'chime:DeleteAttendee',
        ],
        resources: [
          this.formatArn({
            service: 'chime',
            resource: 'meeting',
            resourceName: '*',
          }),
        ],
      })
    );

    // Dashboard triggers flows by invoking the channel adapter (push).
    channelAdapter.grantInvoke(dashboard);

    // Inbound topic → channel adapter.
    inbound.addSubscription(new subs.LambdaSubscription(channelAdapter));

    // ── Media convert (S3-triggered HEIC/JPEG/PNG normalization) ────────
    // Secure webview upload pipeline: browser -> presigned S3 PUT (see
    // dashboard.create_upload_url) -> this Lambda (S3 ObjectCreated event on
    // the raw-uploads/ prefix) -> converted-uploads/ JPEG + Bedrock
    // classification -> DynamoDB status the webview polls. See
    // lambda/media_convert.py's docstring.
    const mediaConvertLogGroup = new logs.LogGroup(this, 'MediaConvertLogGroup', {
      logGroupName: `/aws/lambda/${prefix}-media-convert`,
      retention: logs.RetentionDays.TWO_WEEKS,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    const mediaConvertFn = new lambda.Function(this, 'MediaConvertFn', {
      functionName: `${prefix}-media-convert`,
      runtime: PY_RUNTIME,
      architecture: lambda.Architecture.X86_64, // must match the layers' pinned wheels
      handler: 'media_convert.handler',
      code: appCode,
      layers: [mediaLayer],
      timeout: Duration.seconds(60),
      memorySize: 1024, // Pillow HEIC decode is memory-hungry for large iPhone photos.
      // Measured on Python 3.14 (Max Memory Used): a 12 MP HEIC took 227 MB, a 24 MP one 337 MB.
      environment: {
        ...commonEnv,
        // Called only after a native inbound conversion completes, so the
        // adapter can send a normal RCS confirmation card in bot mode.
        CHANNEL_ADAPTER_FN: channelAdapter.functionName,
      },
      logGroup: mediaConvertLogGroup,
    });
    table.grantReadWriteData(mediaConvertFn);
    // Reads the two upload sources and writes the two converted outputs
    // (media_convert._open_normalized_jpeg get_object; the two put_object calls).
    // No list, delete, tagging or multipart call anywhere in that module.
    mediaConvertFn.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'ReadUploadSources',
        actions: ['s3:GetObject'],
        resources: [rawUploadObjects, nativeRcsObjects],
      })
    );
    mediaConvertFn.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'WriteConvertedOutputs',
        actions: ['s3:PutObject'],
        resources: [convertedUploadObjects, nativeConvertedObjects],
      })
    );
    mediaConvertFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['bedrock:InvokeModel'],
        resources: [bedrockFoundationModelArn, bedrockInferenceProfileArn],
      })
    );
    // The converter sends a completion callback only for native inbound media;
    // the adapter uses it to send the final rich card while BOT mode is active.
    channelAdapter.grantInvoke(mediaConvertFn);

    // Prefixes must match lambda/common.py and lambda/media_convert.py exactly.
    // Webview files use raw-uploads/, while EUM-delivered native RCS files use
    // inbound/rcs/. Keep these notifications separate so setup notification
    // objects under inbound/ never enter the image pipeline.
    bucket.addEventNotification(
      s3.EventType.OBJECT_CREATED_PUT,
      new s3n.LambdaDestination(mediaConvertFn),
      { prefix: `${UPLOAD_RAW_PREFIX}/` }
    );
    bucket.addEventNotification(
      s3.EventType.OBJECT_CREATED_PUT,
      new s3n.LambdaDestination(mediaConvertFn),
      { prefix: `${NATIVE_RCS_MEDIA_PREFIX}/` }
    );

    // ── HTTP API authorizer (gates writes + recipient-data reads) ───────
    const authorizerLogGroup = new logs.LogGroup(this, 'AuthorizerLogGroup', {
      logGroupName: `/aws/lambda/${prefix}-api-authorizer`,
      retention: logs.RetentionDays.TWO_WEEKS,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    const authorizerFn = new lambda.Function(this, 'AuthorizerFn', {
      functionName: `${prefix}-api-authorizer`,
      runtime: PY_RUNTIME,
      architecture: lambda.Architecture.X86_64, // must match the layers' pinned wheels
      handler: 'authorizer.handler',
      code: lambda.Code.fromAsset(LAMBDA_DIR, {
        exclude: ['layer', 'custom_resources', '**/__pycache__'],
      }),
      timeout: Duration.seconds(10),
      environment: { API_KEY_SECRET_ARN: apiKeySecret.secretArn },
      logGroup: authorizerLogGroup,
    });
    apiKeySecret.grantRead(authorizerFn);

    const apiKeyAuthorizer = new HttpLambdaAuthorizer('ApiKeyAuthorizer', authorizerFn, {
      authorizerName: `${prefix}-api-key-authorizer`,
      responseTypes: [HttpLambdaResponseType.SIMPLE],
      identitySource: ['$request.header.x-api-key'],
      // Gateway-side result cache. Denials are cached too, so a rotated key's
      // predecessor can keep working for this long plus the authorizer's own
      // secret cache (SECRET_CACHE_TTL_SECONDS in lambda/authorizer.py).
      // SECURITY.md ("Rotating the API key") has the combined worst case.
      resultsCacheTtl: Duration.minutes(5),
    });

    // ── HTTP API (dashboard + webviews) ─────────────────────────────────
    // Access log for the $default stage: one JSON line for each request that
    // matches a route, in a log group of its own. A CORS preflight is logged
    // too (route key '-'). A request that matches no route writes no line, so
    // the log does not record probes of unknown paths. The line is built from
    // documented HTTP API $context variables only ("Customize HTTP API access
    // logs").
    //
    // It leaves out $context.path, the query string, the user agent and every
    // header on purpose. The raw path carries `ph` (an unsalted hash of the
    // member's phone number), upload ids and tester phone numbers
    // (GET /api/conversations/{ph}, GET /api/uploads/{ph}/{id}/status,
    // DELETE /api/testers/{phone}); the query string carries `ph`, visit tokens
    // and phone numbers (?ph=, ?visit=, ?phone=). $context.routeKey is the route
    // TEMPLATE ("GET /api/conversations/{proxy+}"), so a line says which route
    // was hit and never which member, upload or visit. On a deployed stack a
    // matched request logged the template and a CORS preflight logged '-'. In
    // testing, the free-text fields (error.message, integrationErrorMessage,
    // authorizer.error) held only '-', 'Unauthorized' and 'Forbidden'; review
    // the log lines for your own traffic before sharing them.
    //
    // sourceIp is the one personal datum kept. With one shared API key and an
    // authorizer that returns no principal, it is the only attribute of the
    // caller the gateway has, and without it the log cannot tell a probe from
    // the operator's own 403. It is a member's carrier or home address, or the
    // operator's, so SECURITY.md describes what the log holds, and the group
    // below keeps it for two weeks.
    //
    // Every value is a quoted string, as in the JSON example in the HTTP API
    // logging docs: a variable with no value (integrationLatency on a request
    // the authorizer denied, say) comes through as "-" (observed), which a bare
    // JSON number cannot be.
    const apiAccessLogGroup = new logs.LogGroup(this, 'ApiAccessLogGroup', {
      // /aws/vendedlogs/ is the prefix CloudWatch Logs documents for a group an
      // AWS service delivers to: when the account's log resource policy nears
      // its size cap, CloudWatch Logs enables delivery for groups under this
      // prefix itself. Without it, an account with many delivery-enabled groups
      // can fail the deploy with "Cannot enable logging. Policy document length
      // breaking Cloudwatch Logs Constraints". Lines reached a group under this
      // prefix within 1-2 minutes of a request on a deployed stack. The
      // stack writes no log resource policy; on that deployment a policy scoped
      // to this group (Sid AWSLogDeliveryWrite1) appeared during the stack
      // update, with the call in CloudTrail under CloudFormation's execution
      // role, and the account-level policy list stayed empty. This sample did
      // not check whether cdk destroy removes that policy.
      logGroupName: `/aws/vendedlogs/apigateway/${prefix}-demo-api`,
      retention: logs.RetentionDays.TWO_WEEKS,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    const apiAccessLogFormat = JSON.stringify({
      requestId: '$context.requestId',
      requestTime: '$context.requestTime',
      sourceIp: '$context.identity.sourceIp',
      routeKey: '$context.routeKey',
      httpMethod: '$context.httpMethod',
      status: '$context.status',
      responseLength: '$context.responseLength',
      responseLatency: '$context.responseLatency',
      integrationLatency: '$context.integrationLatency',
      integrationStatus: '$context.integrationStatus',
      integrationErrorMessage: '$context.integrationErrorMessage',
      authorizerError: '$context.authorizer.error',
      errorMessage: '$context.error.message',
      errorResponseType: '$context.error.responseType',
    });
    // A later edit that added the path, the user agent or a request header or
    // query variable would put the conversation hash, a phone number or a visit
    // token into a log with a different retention and audience than the data it
    // came from, so synth refuses.
    const accessLogLeak = apiAccessLogFormat.match(
      /\$context\.path|\$context\.identity\.userAgent|\$context\.requestOverride|\$request\./i
    );
    if (accessLogLeak) {
      throw new Error(
        `The API access log format contains ${accessLogLeak[0]}, which can carry a conversation ` +
          'hash (ph), a phone number or a visit token. Log $context.routeKey (the route ' +
          'template) instead, and leave out the path, query string, headers and user agent.'
      );
    }

    const httpApi = new HttpApi(this, 'Api', {
      apiName: `${prefix}-demo-api`,
      corsPreflight: {
        allowOrigins: ['*'],
        allowMethods: [CorsHttpMethod.ANY],
        allowHeaders: ['Content-Type', 'Authorization', 'X-Api-Key'],
        maxAge: Duration.hours(1),
      },
    });
    // The setting goes on the stage the construct already owns. Creating the
    // stage ourselves (createDefaultStage: false plus an HttpStage) would need a
    // construct id, and an id that is not the one CDK uses gives the stage a new
    // logical id: CloudFormation then creates the replacement before it deletes
    // the first, and two stages named "$default" cannot coexist on one API.
    // Setting the property on the CfnStage the construct already owns keeps the
    // stage's logical id, and AccessLogSettings is an in-place update (observed
    // when an existing stack was updated: the stage kept its creation date and
    // CloudFormation reported only UPDATE events). The check makes an
    // aws-cdk-lib that stops exposing a CfnStage here fail at synth instead of
    // leaving the API without an access log.
    const defaultStage = httpApi.defaultStage?.node.defaultChild;
    if (!(defaultStage instanceof CfnStage)) {
      throw new Error('HttpApi default stage is not a CfnStage; cannot enable access logging');
    }
    defaultStage.accessLogSettings = {
      destinationArn: apiAccessLogGroup.logGroupArn,
      format: apiAccessLogFormat,
    };
    const integration = new HttpLambdaIntegration('DashboardIntegration', dashboard);

    // Unauthenticated routes. Each one is open because something that cannot
    // hold the operator's API key has to call it — a member's in-app webview
    // browser, or an <img> tag — or because it returns only static demo
    // metadata. None of them takes a phone number, and none can be used to
    // enumerate recipients or read a transcript. Three take a conversation
    // reference: GET /api/uploads/{ph}/{id}/status needs a 122-bit uuid4 upload
    // id the member's own webview was given, and POST /api/uploads/presign and
    // GET /api/secure-doc are scoped to a `ph` conversation hash — which is an
    // unsalted hash of the phone number, so see the honest accounting of what
    // that does and does not protect in dashboard_handler.get_secure_doc.
    httpApi.addRoutes({ path: '/', methods: [HttpMethod.ANY], integration });
    // Member's in-app browser opens these; no key available.
    httpApi.addRoutes({ path: '/webview/{proxy+}', methods: [HttpMethod.GET], integration });
    // Static demo metadata: brand tokens and the vignette catalog/templates.
    httpApi.addRoutes({ path: '/api/brand', methods: [HttpMethod.GET], integration });
    httpApi.addRoutes({ path: '/api/vignettes', methods: [HttpMethod.GET], integration });
    httpApi.addRoutes({ path: '/api/vignettes/preview', methods: [HttpMethod.GET], integration });
    // The RCS feature registry (content/rcs-features.json) — documented limits,
    // feature explanations and AWS doc links the dashboard renders as tooltips.
    httpApi.addRoutes({ path: '/api/vignettes/features', methods: [HttpMethod.GET], integration });
    // The deployed backend's version string, rendered beside the frontend's in
    // the dashboard status bar. Open because it is build metadata about this
    // sample — no account, recipient or quota information of any kind — and the
    // status bar has to show it whether or not the operator has yet pasted a
    // working API key, since "which backend am I on?" is the first question
    // asked when the key turns out to be wrong.
    httpApi.addRoutes({ path: '/api/version', methods: [HttpMethod.GET], integration });
    // Media redirect: consumed directly as an <img src> by the dashboard and the
    // upload webview (see web/src/api.ts mediaUrl), and a browser cannot attach
    // an x-api-key header to an image request — so this route cannot sit behind
    // the authorizer. It is instead constrained server-side to an allow-list of
    // key prefixes; see dashboard_handler.get_media_url.
    httpApi.addRoutes({ path: '/api/media', methods: [HttpMethod.GET], integration });
    // Secure webview upload (insurance_upload.py): unauthenticated by design
    // — called from inside a member-facing webview session, which has no
    // way to hold the operator's dashboard API key.
    httpApi.addRoutes({ path: '/api/uploads/presign', methods: [HttpMethod.POST], integration });
    httpApi.addRoutes({ path: '/api/uploads/{proxy+}', methods: [HttpMethod.GET], integration });
    // The outbound counterpart: a short-lived presigned GET for a document that
    // must not cross the carrier network, fetched by the webview that shows it
    // (lambda/webviews/rx-patient-info.html). Same reason it cannot be
    // authenticated — the caller is a member's in-app browser.
    httpApi.addRoutes({ path: '/api/secure-doc', methods: [HttpMethod.GET], integration });
    // EXPERIMENTAL — the WebRTC video visit (lambda/webviews/video-visit.html).
    // Unauthenticated for the same reason as the routes above: the caller is a
    // member's in-app browser session. Unlike those, this one can spend money —
    // Chime attendee-minutes are billed — so the control is a pre-minted,
    // 30-minute, 122-bit visit token plus a hard per-visit join budget, both in
    // lambda/video_visit.py. The endpoint never creates a meeting for an id it
    // was not already given.
    //
    // ping and status carry the presence both clients need: they are what tells
    // the clinician's dashboard that the patient is already waiting in the visit.
    // status returns booleans only, so an unauthenticated caller holding a token
    // learns nothing it did not already have. All GET, because the member's page
    // reports presence with an <img> request — /webview/{proxy+} is GET-only and
    // sendBeacon's POST would be rejected.
    for (const p of ['/api/video/join', '/api/video/ping', '/api/video/status', '/api/video/end']) {
      httpApi.addRoutes({ path: p, methods: [HttpMethod.GET], integration });
    }

    // Authenticated read routes. These disclose registered testers' full E.164
    // phone numbers and names, conversation transcripts (including the body of
    // any verification code that was sent), presigned URLs for member-submitted
    // documents, and the account's RCS spend limits — so they are gated by the
    // same API key as the write routes below. The API hostname is not a secret:
    // common.py builds every in-message webview link from API_BASE_URL and sends
    // it to member handsets, so "hard to guess" is not a control here.
    // The dashboard passes the key on these calls via req(..., authed=true) in
    // web/src/api.ts — both sides must change together.
    for (const p of [
      '/api/health',
      // /api/agent-identity returns the RCS registration's contact phone number
      // and email address — real, operator-owned details rather than the
      // fictional ones in content/brand.md — plus the AWS account id this stack
      // runs in, so it is gated like the rest.
      '/api/agent-identity',
      '/api/conversations',
      '/api/conversations/{proxy+}',
      '/api/testers',
      '/api/testers/names',
      '/api/testers/status',
      '/api/testers/metrics',
      // Custom keywords registered on the RCS agent. A read, but it returns the
      // agent's configured keyword responses, so it sits behind the key with
      // the rest of the operator data.
      '/api/keywords',
      '/api/media/latest',
      '/api/mode',
      // Who is composing a reply right now. Returns conversation hashes and
      // timestamps only — never a phone number — but it is still a list of
      // which registered recipients are active, so it sits behind the key with
      // the rest of the recipient data. The dashboard resolves the hashes to
      // names locally from /api/testers, which it already has.
      '/api/typing',
    ]) {
      httpApi.addRoutes({
        path: p,
        methods: [HttpMethod.GET],
        integration,
        authorizer: apiKeyAuthorizer,
      });
    }

    // Write / action routes: these can send RCS messages to real devices or
    // mutate/delete demo data, so they require the shared API key.
    for (const p of [
      '/api/testers',
      '/api/testers/{proxy+}',
      // POST /api/keywords registers or updates a custom keyword on the agent.
      '/api/keywords',
      '/api/trigger',
      '/api/push',
      '/api/reply',
      '/api/mode',
      '/api/reset',
      // Mints a visit token, sends the invitation card, and returns the token so
      // the operator console can join the same Chime meeting. Authenticated —
      // unlike /api/video/join and /api/video/end above, whose caller is the
      // member's webview and cannot hold the key.
      '/api/video/start',
      // Same, minus the send: a token for previewing the member's own webview
      // from the dashboard, with no handset and no message.
      '/api/video/preview',
    ]) {
      httpApi.addRoutes({
        path: p,
        methods: [HttpMethod.POST, HttpMethod.PUT],
        integration,
        authorizer: apiKeyAuthorizer,
      });
    }

    // DELETE /api/testers/{phone} unregisters a verified test device. Its own
    // route rather than another entry in the loop above, because DELETE is
    // meaningful on this path only — added to the whole list it would accept
    // DELETE /api/trigger and friends and hand them to the handler's fallback.
    httpApi.addRoutes({
      path: '/api/testers/{proxy+}',
      methods: [HttpMethod.DELETE],
      integration,
      authorizer: apiKeyAuthorizer,
    });

    // DELETE /api/keywords/{keyword} removes a custom keyword from the agent.
    // Its own route for the same reason as the tester DELETE above: DELETE is
    // meaningful only on this path, and folding it into the write loop would
    // accept DELETE on every write route and hand it to the handler fallback.
    httpApi.addRoutes({
      path: '/api/keywords/{proxy+}',
      methods: [HttpMethod.DELETE],
      integration,
      authorizer: apiKeyAuthorizer,
    });

    // The channel adapter builds webview links (e.g. .../webview/rx-details) at
    // runtime from this base URL — nothing hardcoded. Injected only here (not on
    // the dashboard, which is the API's integration target) to avoid a CFN cycle.
    channelAdapter.addEnvironment('API_BASE_URL', httpApi.apiEndpoint);

    // ── EUM wiring custom resource ──────────────────────────────────────
    // The RCS agent is created and registered during setup (AGENTS.md), outside
    // this stack. CloudFormation's AWS::SMSVOICE::RcsAgent would create a NEW
    // agent (its create handler calls CreateRcsAgent) rather than adopt that
    // one. A Lambda-backed custom resource therefore enables two-way + inbound
    // media on the existing agent through the API. It also creates the
    // configuration set and its SNS event destination — CloudFormation-
    // manageable too (AWS::SMSVOICE::ConfigurationSet, EventDestinations) but
    // kept here so that one resource sets up all three on deploy and unwinds
    // them on destroy. And it registers the agent's HELP, STOP and UNSTOP
    // keyword replies through the PutKeyword API.
    const eumWiringLogGroup = new logs.LogGroup(this, 'EumWiringLogGroup', {
      logGroupName: `/aws/lambda/${prefix}-eum-wiring`,
      retention: logs.RetentionDays.TWO_WEEKS,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    const eumWiringFn = new lambda.Function(this, 'EumWiringFn', {
      functionName: `${prefix}-eum-wiring`,
      runtime: PY_RUNTIME,
      architecture: lambda.Architecture.X86_64, // must match the layers' pinned wheels
      handler: 'eum_wiring.on_event',
      code: lambda.Code.fromAsset(path.join(LAMBDA_DIR, 'custom_resources')),
      layers: [depsLayer],
      timeout: Duration.minutes(5),
      logGroup: eumWiringLogGroup,
    });
    eumWiringFn.addToRolePolicy(
      new iam.PolicyStatement({
        // CreateConfigurationSet has no resource-level permissions defined by
        // the service (must be created before its ARN can be referenced).
        actions: ['sms-voice:CreateConfigurationSet'],
        resources: ['*'],
      })
    );
    eumWiringFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: [
          'sms-voice:DeleteConfigurationSet',
          'sms-voice:CreateEventDestination',
          'sms-voice:DeleteEventDestination',
          'sms-voice:UpdateEventDestination',
          'sms-voice:GetConfigurationSetEventDestinations',
        ],
        resources: [configSetArn],
      })
    );
    eumWiringFn.addToRolePolicy(
      new iam.PolicyStatement({
        // DescribeRcsAgents is the read a Delete makes to confirm the agent still
        // delivers to this stack's topic before it unwinds anything
        // (eum_wiring._two_way_moved_on).
        actions: ['sms-voice:UpdateRcsAgent', 'sms-voice:DescribeRcsAgents'],
        resources: [rcsAgentArn],
      })
    );
    if (inputs.keywordMessages) {
      // The keyword step (eum_wiring.py, _register_keywords) lists the agent's
      // keywords, writes HELP, STOP and UNSTOP, and on destroy removes UNSTOP.
      // Resource-scoped to the agent ARN for the same reason as the
      // dashboard's keyword grant above. Left out under -c registerKeywords=false,
      // when the step does not run.
      eumWiringFn.addToRolePolicy(
        new iam.PolicyStatement({
          actions: ['sms-voice:DescribeKeywords', 'sms-voice:PutKeyword', 'sms-voice:DeleteKeyword'],
          resources: [rcsAgentArn],
        })
      );
    }
    // Allow passing the two-way roles (SNS publish + inbound media S3 write)
    // to the EUM service.
    eumWiringFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['iam:PassRole'],
        resources: [twoWayRole.roleArn, twoWayMediaRole.roleArn],
      })
    );

    const eumProviderLogGroup = new logs.LogGroup(this, 'EumWiringProviderLogGroup', {
      retention: logs.RetentionDays.TWO_WEEKS,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    const eumProvider = new Provider(this, 'EumWiringProvider', {
      onEventHandler: eumWiringFn,
      logGroup: eumProviderLogGroup,
    });
    const eumWiring = new CustomResource(this, 'EumWiring', {
      serviceToken: eumProvider.serviceToken,
      properties: {
        RcsAgentId: inputs.rcsAgentId,
        ConfigurationSetName: configSetName,
        EventDestinationName: `${prefix}-events-sns`,
        // RCS_ALL is the RCS subscription described in the RCS events guide
        // (see _ensure_event_destination in eum_wiring.py). On a testing agent,
        // delivery and read events are not published to the configuration set
        // destination; they appear once the agent is launched in a country (the
        // RCSMessagesDelivered metric still counts deliveries). That is why the
        // Recipients tab's Delivered/Read columns stay at zero on a testing
        // agent.
        MatchingEventTypes: ['RCS_ALL'],
        // The agent's own event subscription, which is what forwards RCS events
        // to the two-way topic. Independent of MatchingEventTypes above.
        TwoWayRcsEventsEnabled: ['ALL'],
        InboundTopicArn: inbound.topicArn,
        TwoWayRoleArn: twoWayRole.roleArn,
        TwoWayMediaS3BucketName: bucket.bucketName,
        TwoWayMediaS3RoleArn: twoWayMediaRole.roleArn,
        TwoWayMediaS3KeyPrefix: INBOUND_MEDIA_PREFIX,
        // The replies for the agent's HELP, STOP and UNSTOP keywords, built from
        // content/brand.md (config.ts, buildKeywordMessages). Left out under
        // -c registerKeywords=false: without them the custom resource skips the
        // keyword step. Written only over a placeholder, an empty keyword or text
        // this stack wrote before, never over a reply the deployer set; the
        // rules are in eum_wiring._register_keywords.
        ...(inputs.keywordMessages
          ? {
              KeywordHelpMessage: inputs.keywordMessages.help,
              KeywordStopMessage: inputs.keywordMessages.stop,
              KeywordUnstopMessage: inputs.keywordMessages.unstop,
            }
          : {}),
      },
    });
    eumWiring.node.addDependency(inbound, twoWayRole, twoWayMediaRole);

    // ── Outputs ─────────────────────────────────────────────────────────
    new CfnOutput(this, 'ApiUrl', {
      value: httpApi.apiEndpoint,
      description: 'Base URL for the dashboard API (set as web VITE_API_URL).',
    });
    new CfnOutput(this, 'TableName', { value: table.tableName });
    new CfnOutput(this, 'BucketName', { value: bucket.bucketName });
    new CfnOutput(this, 'InboundTopicArn', { value: inbound.topicArn });
    new CfnOutput(this, 'ConfigSetName', { value: configSetName });
    new CfnOutput(this, 'RcsAgentId', { value: inputs.rcsAgentId });
    // Registering the keyword replies never fails the deploy, so this is where a
    // problem shows: "ok (...)", "skipped", or "error (...)" with the AWS error
    // code. The full error is in the EumWiringFn log group.
    new CfnOutput(this, 'KeywordsStatus', {
      value: eumWiring.getAttString('KeywordsStatus'),
      description: 'Result of registering the HELP, STOP and UNSTOP keyword replies on the RCS agent.',
    });
    new CfnOutput(this, 'ApiKeySecretName', {
      value: apiKeySecret.secretName,
      description: 'Secrets Manager secret holding the API key for the write routes and the recipient-data reads. ' +
        'Retrieve with: aws secretsmanager get-secret-value --secret-id <this value> ' +
        `--query SecretString --output text --region ${this.region}`,
    });
  }
}
