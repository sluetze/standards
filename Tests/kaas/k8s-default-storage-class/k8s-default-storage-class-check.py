#!/usr/bin/env python3

"""PersistentVolumeClaims checker

Return codes:
0:    Default StorageClass is available, and setup to SCS standard
1:    Not able to connect to k8s api
2:    Kubeconfig not set
3:    Conflicting Resources

31:   Default storage class has no provisioner
32:   None or more then one default Storage Class is defined
33:   CSI provider does not belong to the recommended providers
(34:  No CSI provider found)

41:   Not able to bind PersitantVolume to PersitantVolumeClaim
42:   ReadWriteOnce is not a supported access mode

All return codes between (and including) 1-19 as well as all return codes ending on 9
can be seen as failures.

Check given cloud for conformance with SCS standard regarding
Default StorageClass and PersistentVolumeClaims, to be found under /Standards/scs-0211-v1-kaas-default-storage-class.md

"""
import getopt
import inspect
import json
import logging
import logging.config
import os
import sys
import time

from helper import (
    SCSTestException,
    gen_sonobuoy_result_file,
    initialize_logging,
    print_usage,
    setup_k8s_client,
)
from kubernetes import client
from kubernetes.client.rest import ApiException

logger = logging.getLogger("k8s-default-storage-class-check")

NUM_RETRIES = 30
NAMESPACE = "default"
PVC_NAME = "test-k-pvc"
PV_NAME = "test-k-pv"
POD_NAME = "test-k-pod"
ALLOWED_CSI_PROV = ["cinder", "rookCeph", "longhorn"]


def check_default_storageclass(k8s_client_storage):
    api_response = k8s_client_storage.list_storage_class(_preload_content=False)
    storageclasses = api_response.read().decode("utf-8")
    storageclasses_dict = json.loads(storageclasses)

    ndefault_class = 0

    for item in storageclasses_dict["items"]:
        storage_class_name = item["metadata"]["name"]
        annotations = item["metadata"]["annotations"]

        if annotations["storageclass.kubernetes.io/is-default-class"] == "true":
            ndefault_class += 1
            default_storage_class = storage_class_name
            provisioner = item["provisioner"]

    if provisioner == "kubernetes.io/no-provisioner":
        raise SCSTestException(
            f"Provisioner is set to: {provisioner}.",
            "This means the default storage class has no provisioner.",
            return_code=31,
        )

    if ndefault_class != 1:
        raise SCSTestException(
            "More then one or none default StorageClass is defined! ",
            f"Number of defined default StorageClasses = {ndefault_class} ",
            return_code=32,
        )

    logger.info(f"One default Storage Class found:'{default_storage_class}'")
    return default_storage_class


def create_pvc_pod(k8s_api_instance, storage_class, pvc_name = PVC_NAME, pod_name = POD_NAME, pv_name = PV_NAME, namespace = NAMESPACE, num_retries = NUM_RETRIES):
    """
    1. Create PersistantVolumeClaim
    2. Create pod which uses the PersitantVolumeClaim
    """
    # 1. Create PersistantVolumeClaim
    logger.debug(f"create pvc: {pvc_name}")

    pvc_meta = client.V1ObjectMeta(name=pvc_name)
    pvc_resources = client.V1ResourceRequirements(
        requests={"storage": "1Gi"},
    )
    pvc_spec = client.V1PersistentVolumeClaimSpec(
        access_modes=["ReadWriteOnce"],
        storage_class_name=storage_class,
        resources=pvc_resources,
    )
    body_pvc = client.V1PersistentVolumeClaim(
        api_version="v1", kind="PersistentVolumeClaim", metadata=pvc_meta, spec=pvc_spec
    )

    api_response = k8s_api_instance.create_namespaced_persistent_volume_claim(
        NAMESPACE, body_pvc
    )

    # 2. Create a pod which makes use of the PersitantVolumeClaim
    logger.debug(f"create pod: {pod_name}")

    pod_vol = client.V1Volume(
        name=PV_NAME,
        persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(pvc_name),
    )
    pod_con = client.V1Container(
        name="nginx",
        image="nginx",
        ports=[client.V1ContainerPort(container_port=80)],
        volume_mounts=[
            client.V1VolumeMount(name=PV_NAME, mount_path="/usr/share/nginx/html")
        ],
    )
    pod_spec = client.V1PodSpec(volumes=[pod_vol], containers=[pod_con])
    pod_body = client.V1Pod(
        api_version="v1",
        kind="Pod",
        metadata=client.V1ObjectMeta(name=pod_name),
        spec=pod_spec,
    )

    api_response = k8s_api_instance.create_namespaced_pod(
        NAMESPACE, pod_body, _preload_content=False
    )
    pod_info = json.loads(api_response.read().decode("utf-8"))
    pod_status = pod_info["status"]["phase"]

    retries = 0
    while pod_status != "Running" and retries <= num_retries:
        api_response = k8s_api_instance.read_namespaced_pod(
            POD_NAME, NAMESPACE, _preload_content=False
        )
        pod_info = json.loads(api_response.read().decode("utf-8"))
        pod_status = pod_info["status"]["phase"]
        logger.debug(f"retries:{retries} status:{pod_status}")
        time.sleep(1)
        retries += 1

    if pod_status != "Running":
        raise SCSTestException(
            "pod is not Running not able to setup test Environment",
            return_code=13,
        )
    return 0


def check_default_persistentvolumeclaim_readwriteonce(k8s_api_instance):
    """
    3. Check if PV got succesfully created using ReadWriteOnce
    """
    # 3. Check if PV got succesfully created using ReadWriteOnce
    logger.debug("check if the created PV supports ReadWriteOnce")

    api_response = k8s_api_instance.list_persistent_volume(_preload_content=False)

    pv_info = json.loads(api_response.read().decode("utf-8"))
    pv_list = pv_info["items"]

    logger.debug("searching for corresponding pv")
    for pv in pv_list:
        logger.debug(f"parsing pv: {pv['metadata']['name']}")
        if pv["spec"]["claimRef"]["name"] == PVC_NAME:
            logger.debug(f"found pv to pvc: {PVC_NAME}")

            if pv["status"]["phase"] != "Bound":
                raise SCSTestException(
                    "Not able to bind pv to pvc",
                    return_code=41,
                )

            if "ReadWriteOnce" not in pv["spec"]["accessModes"]:
                raise SCSTestException(
                    "access mode 'ReadWriteOnce' is not supported",
                    return_code=42,
                )
    return 0


def check_csi_provider(k8s_core_api):
    pods = k8s_core_api.list_namespaced_pod(namespace="kube-system")
    csi_list = []
    for pod in pods.items:
        if "csi" in pod.metadata.name:
            if pod.metadata.name in ALLOWED_CSI_PROV:
                csi_list.append(pod.metadata.name)
                logger.info(f"CSI-Provider: {pod.metadata.name}")
            else:
                raise SCSTestException(
                    f"CSI-Provider: {pod.metadata.name} not recommended",
                    return_code=33,
                )
        else:
            logger.info("CSI-Provider: No CSI Provider found.")
            # raise SCSTestException(
            #     "CSI-Provider: No CSI Provider found.",
            #     return_code=34,
            # )
    return 0


class TestEnvironment:
    def __init__(self, kubeconfig):
        self.namespace = NAMESPACE
        self.pod_name = POD_NAME
        self.pvc_name = PVC_NAME
        self.k8s_core_api = None
        self.return_code = 0
        self.return_message = "return_message: FAILED"
        self.kubeconfig = kubeconfig

    def prepare(self):
        """
        Sets up k8s client in preparation of the testing.
        Checks whether the test pod and/or pvc already exists in the test namespace.
        If so, it returns True indecating cleanup has to be executed first.
        """
        try:
            logger.debug("setup_k8s_client(kubeconfig)")
            self.k8s_core_api, self.k8s_storage_api = setup_k8s_client(self.kubeconfig)
        except Exception as exception_message:
            logger.error(f"L{inspect.currentframe().f_lineno} {exception_message}")
            self.return_message = f"{exception_message}"
            self.return_code = 1

        logger.debug("Checking Environment for Leftovers")
        try:
            pod_list = self.k8s_core_api.list_namespaced_pod(namespace=self.namespace)
            for pod in pod_list.items:
                if pod.metadata.name == self.pod_name:
                    logger.debug(
                        f"POD '{self.pod_name}' exists in namespace '{self.namespace}'"
                    )
                    return True
            pvc_list = self.k8s_core_api.list_namespaced_persistent_volume_claim(
                namespace=self.namespace
            )
            for pvc in pvc_list.items:
                if pvc.metadata.name == self.pvc_name:
                    logger.debug(
                        f"PVC '{self.pvc_name}' exists in namespace '{self.namespace}'"
                    )
                    return True
            return False
        except ApiException as e:
            logger.error(f"Error preparing Environment: {e}")
            return False

    def clean(self):
        api_response = None
        try:
            logger.debug(f"delete pod:{self.pod_name}")
            api_response = self.k8s_core_api.delete_namespaced_pod(
                self.pod_name, self.namespace
            )
        except Exception:
            logger.error(f"The pod {self.pod_name} couldn't be deleted.", exc_info=True)
        try:
            logger.debug(f"delete pvc:{self.pvc_name}")
            api_response = self.k8s_core_api.delete_namespaced_persistent_volume_claim(
                self.pvc_name, self.namespace
            )
        except Exception:
            logger.error(f"The PVC {self.pvc_name} couldn't be deleted.", exc_info=True)
        return api_response

    def __enter__(self):
        retries = 0
        while retries <= 2:
            if self.prepare():
                self.clean()
                logger.debug(
                    f"Deleting Leftovers in namespace {self.namespace} from previous test runs"
                )
                time.sleep(2)
            else:
                logger.debug(f"Entering the context {self.k8s_core_api}")
                return self
            retries += 1
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.clean()
        if self.return_code == 0:
            self.return_message = "all tests passed"
        if isinstance(exc_value, SCSTestException):
            self.return_message = exc_value.args[0]
            self.return_code = exc_value.return_code
            logger.debug(
                f"SCSTestException occurred with return_code: {self.return_code}"
            )
        else:
            # No specific exception, handle normally returnmessage aus exception übernehmen, dann kann return_code
            logger.debug(f"Exiting the context with return_code: {self.return_code}")
        logger.debug(f"{self.return_message}")

        gen_sonobuoy_result_file(
            self.return_code, self.return_message, os.path.basename(__file__)
        )
        logger.debug(f"Exiting the context {self.k8s_core_api}")
        if exc_type:
            logger.error(f"An exception occurred: {exc_value}")
        # Return True if the exception should be suppressed, otherwise False
        return False


def main(argv):
    initialize_logging()
    try:
        opts, args = getopt.gnu_getopt(argv, "k:hd:", ["kubeconfig=", "help", "debug"])
    except getopt.GetoptError as exc:
        logger.error(f"{exc}", file=sys.stderr)
        print_usage()
        return 1

    kubeconfig = None

    for opt in opts:
        if opt[0] == "-h" or opt[0] == "--help":
            print_usage()
            return 0
        if opt[0] == "-k" or opt[0] == "--kubeconfig":
            kubeconfig = opt[1]
        if opt[0] == "-d" or opt[0] == "--debug":
            logging.getLogger().setLevel(logging.DEBUG)
    if not kubeconfig:
        logger.critical("You need to have OS_CLOUD set or pass --kubeconfig=CLOUD.")
        return 2

    with TestEnvironment(kubeconfig) as env:
        # Check if default storage class is defined (MANDATORY)
        k8s_core_api = env.k8s_core_api

        try:
            logger.debug("check_default_storageclass()")
            default_class_name = check_default_storageclass(env.k8s_storage_api)
        except SCSTestException as test_exception: # delete
            logger.error(f"L{inspect.currentframe().f_lineno} {test_exception}")
            env.return_message = f"{test_exception}"
            env.return_code = test_exception.return_code
        except Exception as exception_message: # nochmal prüfen ob SCSTest spezifischer
            logger.error(f"L{inspect.currentframe().f_lineno} {exception_message}")
            env.return_message = f"{exception_message}"
            env.return_code = 1

        try:
            env.return_code = create_pvc_pod(k8s_core_api, default_class_name)
        except ApiException as api_exception:
            if api_exception.status == 409:
                logger.info(
                    "conflicting resources, "
                    "try to clean up left overs, then start again"
                )
                env.return_code = 3
                env.return_message = "(409) conflicting resources"
                return
            else:
                logger.info(f"An API error occurred: {api_exception}")
                env.return_code = 1

        logger.info(
            "Check if default_persistent volume has ReadWriteOnce defined (MANDATORY)"
        )
        env.return_code = check_default_persistentvolumeclaim_readwriteonce(
            k8s_core_api
        )

        env.return_code = check_csi_provider(env.k8s_core_api)
        logger.debug(f"CSI Provider check: {env.return_code}")
    return env.return_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
