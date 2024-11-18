from projen.awscdk import AwsCdkPythonApp

project = AwsCdkPythonApp(
    author_email="nick.arnold@coxautoinc.com",
    author_name="Nick Arnold",
    cdk_version="2.1.0",
    module_name="twitch_streams",
    name="twitch-streams",
    version="0.1.0",
)

project.synth()