---
title: Kubernetes Logging/Monitoring/Tracing
type: Decision Record
status: Draft
track: KaaS
---


## Motivation

Either as an operators or as an end users of a Kubernetes cluster, at some point you will need to debug useful information.
In order to obtain this information, mechanisms SHOULD be available to retrieve this information.
These mechanisms consist of:
* Logging
* Monitoring
* Tracing

The aim of this decision record is to examine how Kubernetes handles thoes mechanisms.
Derived from this, this decision record provides a suggestion on how a Kubernetes cluster SHOULD be configured in order to provide meaningful and comprehensible information via logging, monitoring and tracing.


## Decision

A Kubernetes cluster MUST provide both monitoring and logging. 
In addition, a Kubernetes cluster MAY provide traceability mechanisms, as this is important for time-based troubleshooting. 
Therefore, a standardized concept for the setup of the overall mechanisms as well as the resources to be consumed MUST be defined.

This concept SHALL define monitoring and logging in a federated structure.
Therefore, a monitoring and logging stack MUST be deployed on each k8s cluster. 
A central monitoring can then fetch data from the clusters individual monitoring stacks.


### Monitoring

> see: [Metrics For Kubernetes System Components][system-metrics]
> see: [Metrics for Kubernetes Object States][kube-state-metrics]


SCS KaaS infrastructure monitoring SHOULD be used as a diagnostic tool to alert operators and end users to system-related issues by analyzing metrics.
Therefore, it includes the collection and visualization of the corresponding metrics.
Optionally, an alerting mechanism COULD also be standardized.
This SHOULD contain a minimal set of important metrics that signal problematic conditions of a cluster in any case. 

> Describe one examples here in more detail





[k8s-debug]: https://kubernetes.io/docs/tasks/debug/
[prometheus-operator]: https://github.com/prometheus-operator/prometheus-operator
[k8s-metrics]: https://github.com/kubernetes/metrics
[system-metrics]: https://kubernetes.io/docs/concepts/cluster-administration/system-metrics/
[system-metrics_metric-lifecycle]: https://kubernetes.io/docs/concepts/cluster-administration/system-metrics/#metric-lifecycle
[kube-state-metrics]: https://kubernetes.io/docs/concepts/cluster-administration/kube-state-metrics/
[k8s-deprecating-a-metric]: https://kubernetes.io/docs/reference/using-api/deprecation-policy/#deprecating-a-metric
[k8s-show-hidden-metrics]: https://kubernetes.io/docs/concepts/cluster-administration/system-metrics/#show-hidden-metrics
[system-traces]: https://kubernetes.io/docs/concepts/cluster-administration/system-traces/
[system-logs]: https://kubernetes.io/docs/concepts/cluster-administration/system-logs/
[monitor-node-health]: https://kubernetes.io/docs/tasks/debug/debug-cluster/monitor-node-health/
[k8s-logging]: https://kubernetes.io/docs/concepts/cluster-administration/logging/