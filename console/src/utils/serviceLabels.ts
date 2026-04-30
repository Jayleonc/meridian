import type { ServiceInfo } from "../api/client";

export function serviceSourceLabel(source?: string) {
  switch (source) {
    case "supervisor":
      return "supervisor";
    case "static":
      return "静态配置";
    case "probe_logs":
      return "Probe 日志目录";
    case "supervisor_logs":
      return "supervisor 日志目录";
    case "atlas":
      return "Atlas 服务发现";
    case "local":
      return "本机日志目录";
    default:
      return source || "未知来源";
  }
}

export function serviceStatusLabel(status?: string) {
  switch (status) {
    case "RUNNING":
      return "运行中";
    case "OBSERVED":
      return "日志可观测";
    case "STOPPED":
      return "已停止";
    case "FATAL":
      return "异常";
    default:
      return status || "未知";
  }
}

export function serviceStatusBadge(status?: string) {
  switch (status) {
    case "RUNNING":
      return "badge-emerald";
    case "OBSERVED":
      return "badge-teal";
    case "STOPPED":
    case "FATAL":
      return "badge-coral";
    default:
      return "badge-dim";
  }
}

export function serviceDatabases(service: ServiceInfo) {
  return service.database_list ?? service.databases ?? [];
}
