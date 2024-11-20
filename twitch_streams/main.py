import os
from aws_cdk import Stack

import aws_cdk.aws_ssm as ssm
import logging

from aws_cdk import aws_kinesis as kinesis
from aws_cdk import CfnOutput
from aws_cdk import aws_route53 as r53
from aws_cdk import aws_route53_targets
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_apigateway as apigw
from aws_cdk import aws_apigatewayv2 as apigwv2
from aws_cdk.aws_apigatewayv2_integrations import WebSocketLambdaIntegration

from aws_cdk import aws_lambda
from constructs import Construct

log = logging.getLogger(__name__)
ENV = os.getenv('ENV', 'dev')
SUBDOMAIN = 'twitch-streams'
DOMAIN = 'nickswiss.io'


class CustomSubDomain(Construct):

    def __init__(
            self,
            scope,
            construct_id: str,
            tld_zone_id: str,
            tld_zone_name: str,
            sub_domain: str
    ):
        super().__init__(scope, construct_id)
        self.sub_domain = sub_domain
        self.tld_zone_id = tld_zone_id
        self.tld_zone_name = tld_zone_name
        self.full_domain = f"{self.sub_domain}.{self.tld_zone_name}"
        self.parent_hosted_zone = r53.HostedZone.from_hosted_zone_attributes(
            self,
            f"parent-hosted-zone",
            hosted_zone_id=self.tld_zone_id,
            zone_name=self.tld_zone_name,
        )
        self.hosted_zone = r53.HostedZone(
            self,
            f"{self.full_domain}-hosted-zone",
            zone_name=self.full_domain,
        )
        self.ns_record = r53.NsRecord(
            self,
            f"{self.sub_domain}-parent-{self.tld_zone_name}-NSRecord",
            zone=self.parent_hosted_zone,
            record_name=self.full_domain,
            values=self.hosted_zone.hosted_zone_name_servers,
        )
        self.cert = acm.Certificate(
            self,
            f"{self.full_domain}-certificate",
            domain_name=self.full_domain,
            certificate_name=f"{self.full_domain} subdomain wildcard cert",
            subject_alternative_names=[
                f"*.{self.full_domain}"
            ],
            validation=acm.CertificateValidation.from_dns(self.hosted_zone)
        )


class KinesisGateway(Construct):

    def __init__(
            self,
            scope,
            construct_id: str,
            certificate: acm.Certificate,
            domain_name: str,
            hosted_zone: r53.HostedZone,
    ):
        super().__init__(scope, construct_id)
        # Kinesis Stream
        self.stream = kinesis.Stream(
            self,
            "twitch-chat-stream",
            stream_name="twitch-chat-stream"
        )
        self.connect_handler = aws_lambda.Function(
            self,
            "twitch-stream-connect-handler",
            handler="connect.handle_connect",
            runtime=aws_lambda.Runtime.PYTHON_3_11,
            code=aws_lambda.Code.from_asset("lambda")
        )
        self.disconnect_handler = aws_lambda.Function(
            self,
            "twitch-stream-disconnect-handler",
            handler="disconnect.handle_disconnect",
            runtime=aws_lambda.Runtime.PYTHON_3_11,
            code=aws_lambda.Code.from_asset("lambda")
        )
        self.default_handler = aws_lambda.Function(
            self,
            "twitch-stream-default-handler",
            handler="default.handle_default",
            runtime=aws_lambda.Runtime.PYTHON_3_11,
            code=aws_lambda.Code.from_asset("lambda")
        )
        self.web_socket_api = apigwv2.WebSocketApi(
            self,
            "twitch-stream-websocket-api",
            connect_route_options=apigwv2.WebSocketRouteOptions(
                integration=WebSocketLambdaIntegration(
                    "ConnectIntegration",
                    self.connect_handler
                )
            ),
            disconnect_route_options=apigwv2.WebSocketRouteOptions(
                integration=WebSocketLambdaIntegration(
                    "DisconnectIntegration",
                    self.disconnect_handler
                )
            ),
            default_route_options=apigwv2.WebSocketRouteOptions(
                integration=WebSocketLambdaIntegration(
                    "DefaultIntegration",
                    self.default_handler
                )
            )
        )
        # custom_domain_record = r53.ARecord(
        #     self,
        #     f'{domain_name}-api-ARecord',
        #     zone=hosted_zone,
        #     record_name=domain_name,
        #     target=r53.RecordTarget.from_alias(
        #         aws_route53_targets.ApiGateway(self.web_socket_api)
        #     )
        # )


class MyStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        tld_hosted_zone_id = ssm.StringParameter.value_for_string_parameter(
            self,
            f"/nickswiss.io/hosted-zone-id"
        )
        sub_domain = CustomSubDomain(
            self,
            "custom-sub-domain",
            tld_hosted_zone_id,
            DOMAIN,
            SUBDOMAIN
        )

        base_lambda = aws_lambda.Function(
            self,
            'ApiLambda',
            handler='app.handler',
            runtime=aws_lambda.Runtime.PYTHON_3_11,
            code=aws_lambda.Code.from_asset('lambda')
        )

        # Define the API Gateway resource
        api = apigw.LambdaRestApi(
            self,
            f"api.{sub_domain.full_domain}-lambda-rest-api",
            domain_name=apigw.DomainNameOptions(
                certificate=sub_domain.cert,
                domain_name=f'api.{sub_domain.full_domain}',
            ),
            handler=base_lambda,
            proxy=False,
        )
        # Define the '/hello' resource with a GET method
        v1_resource = api.root.add_resource("v1")
        v1_resource.add_resource("health").add_method("GET")

        custom_domain_record = r53.ARecord(
            self,
            f'api.{sub_domain.full_domain}-api-ARecord',
            zone=sub_domain.hosted_zone,
            record_name=f'api.{sub_domain.full_domain}',
            target=r53.RecordTarget.from_alias(aws_route53_targets.ApiGateway(api))
        )

        kinesis_gateway = KinesisGateway(
            self,
            "twitch-chat-kinesis-gateway",
            sub_domain.cert,
            f'kinesis.{sub_domain.full_domain}',
            sub_domain.hosted_zone
        )
        # Granting role permission to read stream
        # lambda_role = iam.Role(self, "Role",
        #                        assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        #                        description="Example role..."
        #                        )
        #
        # stream = kinesis.Stream(self, "MyEncryptedStream",
        #                         encryption=kinesis.StreamEncryption.KMS
        #                         )
        #
        # # give lambda permissions to read stream
        # stream.grant_read(lambda_role)
        CfnOutput(self, "API Gateway ID", value=api.rest_api_id)
        CfnOutput(self, "API Gateway URL", value=api.url)
        CfnOutput(self, "Custom Domain", value=sub_domain.full_domain)
        CfnOutput(self, "Custom Domain Hosted Zone", value=sub_domain.hosted_zone.zone_name)
        CfnOutput(self, "Custom Domain Certificate", value=sub_domain.cert.certificate_arn)
        CfnOutput(self, "Custom Domain API Gateway Record", value=custom_domain_record.domain_name)
        CfnOutput(self, "Custom Domain API Gateway URL", value=api.url)
        CfnOutput(self, "Healthcheck URL", value=f"{api.url}/v1/health")
