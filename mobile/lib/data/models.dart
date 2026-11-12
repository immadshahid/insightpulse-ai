// Plain data classes parsed from the API's JSON (no code generation).

double _d(Object? v) => (v as num?)?.toDouble() ?? 0;
double? _dn(Object? v) => (v as num?)?.toDouble();
List<T> _list<T>(Object? v, T Function(Map<String, dynamic>) f) =>
    ((v as List?) ?? const []).map((e) => f(e as Map<String, dynamic>)).toList();
Map<String, dynamic> _map(Object? v) => (v as Map?)?.cast<String, dynamic>() ?? {};

class AuthResult {
  AuthResult({required this.token, required this.email});

  factory AuthResult.fromJson(Map<String, dynamic> j) =>
      AuthResult(token: j['access_token'] as String, email: _map(j['user'])['email'] as String);

  final String token;
  final String email;
}

class DatasetSummary {
  DatasetSummary({
    required this.id,
    required this.name,
    required this.status,
    required this.rowCount,
    this.qualityScore,
    this.dateMin,
    this.dateMax,
    this.currency,
  });

  factory DatasetSummary.fromJson(Map<String, dynamic> j) => DatasetSummary(
        id: j['id'] as String,
        name: j['name'] as String,
        status: j['status'] as String,
        rowCount: (j['row_count'] as num).toInt(),
        qualityScore: (j['quality_score'] as num?)?.toInt(),
        dateMin: j['date_min'] as String?,
        dateMax: j['date_max'] as String?,
        currency: j['currency'] as String?,
      );

  final String id;
  final String name;
  final String status;
  final int rowCount;
  final int? qualityScore;
  final String? dateMin;
  final String? dateMax;
  final String? currency;

  bool get isReady => status == 'ready';
}

class ColumnInfo {
  ColumnInfo({required this.name, required this.kind, required this.samples, required this.missingPct});

  factory ColumnInfo.fromJson(Map<String, dynamic> j) => ColumnInfo(
        name: j['name'] as String,
        kind: j['kind'] as String,
        samples: ((j['sample_values'] as List?) ?? const []).map((e) => '$e').toList(),
        missingPct: _d(j['missing_pct']),
      );

  final String name;
  final String kind;
  final List<String> samples;
  final double missingPct;
}

class QualityIssue {
  QualityIssue({required this.severity, required this.message});

  factory QualityIssue.fromJson(Map<String, dynamic> j) =>
      QualityIssue(severity: j['severity'] as String, message: j['message'] as String);

  final String severity;
  final String message;
}

class QualityReport {
  QualityReport({required this.score, required this.label, required this.issues});

  factory QualityReport.fromJson(Map<String, dynamic> j) => QualityReport(
        score: (j['score'] as num).toInt(),
        label: j['label'] as String,
        issues: _list(j['issues'], QualityIssue.fromJson),
      );

  final int score;
  final String label;
  final List<QualityIssue> issues;
}

class DatasetProfile {
  DatasetProfile({
    required this.dataset,
    required this.columns,
    required this.mapping,
    required this.mappingSource,
    required this.roles,
    required this.requiredRoles,
    this.quality,
    this.error,
  });

  factory DatasetProfile.fromJson(Map<String, dynamic> j) {
    final roles = ((j['roles'] as List?) ?? const []).cast<String>();
    final m = _map(j['mapping']);
    return DatasetProfile(
      dataset: DatasetSummary.fromJson(_map(j['dataset'])),
      columns: _list(_map(j['profile'])['columns'], ColumnInfo.fromJson),
      mapping: {for (final r in roles) r: m[r] as String?},
      mappingSource: (m['source'] as String?) ?? 'heuristic',
      roles: roles,
      requiredRoles: ((j['required_roles'] as List?) ?? const []).cast<String>(),
      quality: j['quality'] == null ? null : QualityReport.fromJson(_map(j['quality'])),
    );
  }

  final DatasetSummary dataset;
  final List<ColumnInfo> columns;

  /// role -> column name (or null).
  final Map<String, String?> mapping;
  final String mappingSource;
  final List<String> roles;
  final List<String> requiredRoles;
  final QualityReport? quality;
  final String? error;

  /// column name -> role, the inverse of [mapping].
  Map<String, String> get roleByColumn => {
        for (final e in mapping.entries)
          if (e.value != null) e.value!: e.key,
      };
}

class KpiCard {
  KpiCard({
    required this.key,
    required this.label,
    required this.display,
    this.value = 0,
    this.previous,
    this.changePct,
    this.direction,
    this.spark = const [],
  });

  factory KpiCard.fromJson(Map<String, dynamic> j) => KpiCard(
        key: j['key'] as String,
        label: j['label'] as String,
        display: j['display'] as String,
        value: _d(j['value']),
        previous: _dn(j['previous']),
        changePct: _dn(j['change_pct']),
        direction: j['direction'] as String?,
        spark: [for (final v in (j['spark'] as List? ?? const [])) _d(v)],
      );

  final String key;
  final String label;
  final String display;
  final double value;
  final double? previous;
  final double? changePct;
  final String? direction;

  /// Small trend series over the current period, oldest first.
  final List<double> spark;

  bool get isMoney => key == 'revenue' || key == 'avg_order_value';
}

/// Current and previous date windows of a dashboard period (ISO dates).
class PeriodWindow {
  const PeriodWindow({
    required this.start,
    required this.end,
    required this.prevStart,
    required this.prevEnd,
    this.previousComplete = true,
  });

  factory PeriodWindow.fromJson(Map<String, dynamic> j) => PeriodWindow(
        start: DateTime.parse(j['start'] as String),
        end: DateTime.parse(j['end'] as String),
        prevStart: DateTime.parse(j['prev_start'] as String),
        prevEnd: DateTime.parse(j['prev_end'] as String),
        previousComplete: j['previous_complete'] as bool? ?? true,
      );

  final DateTime start;
  final DateTime end;
  final DateTime prevStart;
  final DateTime prevEnd;

  /// False when the data does not reach back over the whole previous period.
  final bool previousComplete;
}

class Insight {
  Insight({
    required this.id,
    required this.kind,
    required this.category,
    required this.tag,
    required this.headline,
    required this.whyItMatters,
    this.chartUrl,
    this.narrative,
  });

  factory Insight.fromJson(Map<String, dynamic> j) => Insight(
        id: j['id'] as String,
        kind: j['kind'] as String,
        category: j['category'] as String,
        tag: j['tag'] as String,
        headline: j['headline'] as String,
        whyItMatters: j['why_it_matters'] as String,
        chartUrl: j['chart_url'] as String?,
        narrative: j['narrative'] as String?,
      );

  final String id;
  final String kind;
  final String category;
  final String tag;
  final String headline;
  final String whyItMatters;
  final String? chartUrl;
  final String? narrative;

  bool get isAnomaly => category == 'anomalies';
}

class InsightFeed {
  InsightFeed({required this.items, required this.narratives});

  factory InsightFeed.fromJson(Map<String, dynamic> j) => InsightFeed(
        items: _list(j['items'], Insight.fromJson),
        narratives: (j['narratives'] as String?) ?? 'off',
      );

  final List<Insight> items;
  final String narratives;

  bool get isPending => narratives == 'pending';
}

class Dashboard {
  Dashboard({
    required this.period,
    required this.kpis,
    required this.summary,
    required this.summarySource,
    required this.summaryStatus,
    required this.topInsights,
    required this.trendChartUrl,
    required this.forecastStatus,
    this.forecastNote,
    this.currency,
    this.window,
  });

  factory Dashboard.fromJson(Map<String, dynamic> j) {
    final s = _map(j['ai_summary']);
    final f = _map(j['forecast']);
    return Dashboard(
      period: j['period'] as String,
      kpis: _list(j['kpis'], KpiCard.fromJson),
      summary: s['text'] as String? ?? '',
      summarySource: s['source'] as String? ?? 'template',
      summaryStatus: s['status'] as String? ?? 'off',
      topInsights: _list(j['top_insights'], Insight.fromJson),
      trendChartUrl: _map(j['charts'])['revenue_trend'] as String?,
      forecastStatus: f['status'] as String? ?? 'unavailable',
      forecastNote: f['accuracy_note'] as String?,
      currency: j['currency'] as String?,
      window: j['window'] == null ? null : PeriodWindow.fromJson(_map(j['window'])),
    );
  }

  final String period;
  final List<KpiCard> kpis;
  final String summary;
  final String summarySource;
  final String summaryStatus;
  final List<Insight> topInsights;
  final String? trendChartUrl;
  final String forecastStatus;
  final String? forecastNote;
  final String? currency;
  final PeriodWindow? window;

  /// Still waiting on a background job (forecast or AI summary).
  bool get isPending => forecastStatus == 'pending' || summaryStatus == 'pending';
}

class Job {
  Job({required this.id, required this.status, this.result, this.error});

  factory Job.fromJson(Map<String, dynamic> j) => Job(
        id: j['id'] as String,
        status: j['status'] as String,
        result: j['result'] == null ? null : _map(j['result']),
        error: j['error'] as String?,
      );

  final String id;
  final String status;
  final Map<String, dynamic>? result;
  final String? error;

  bool get isDone => status == 'succeeded' || status == 'failed';
}

class ForecastResult {
  ForecastResult({
    required this.target,
    required this.targetLabel,
    required this.horizonDays,
    required this.model,
    required this.total,
    required this.totalLower,
    required this.totalUpper,
    required this.accuracyNote,
    this.changePct,
    this.message,
    this.chartUrl,
    this.currency,
  });

  factory ForecastResult.fromJson(Map<String, dynamic> j) => ForecastResult(
        target: j['target'] as String,
        targetLabel: j['target_label'] as String,
        horizonDays: (j['horizon_days'] as num).toInt(),
        model: j['model'] as String,
        total: _d(j['total']),
        totalLower: _d(j['total_lower']),
        totalUpper: _d(j['total_upper']),
        accuracyNote: j['accuracy_note'] as String? ?? '',
        changePct: _dn(j['change_pct']),
        message: j['message'] as String?,
        chartUrl: j['chart_url'] as String?,
        currency: j['currency'] as String?,
      );

  final String target;
  final String targetLabel;
  final int horizonDays;
  final String model;
  final double total;
  final double totalLower;
  final double totalUpper;
  final String accuracyNote;
  final double? changePct;
  final String? message;
  final String? chartUrl;
  final String? currency;
}

class WhatIfResult {
  WhatIfResult({
    required this.changePct,
    required this.unitsChangePct,
    required this.revenueChangePct,
    required this.baselineRevenue,
    required this.scenarioRevenue,
    required this.notes,
  });

  factory WhatIfResult.fromJson(Map<String, dynamic> j) => WhatIfResult(
        changePct: _d(j['change_pct']),
        unitsChangePct: _d(j['units_change_pct']),
        revenueChangePct: _d(j['revenue_change_pct']),
        baselineRevenue: _d(j['baseline_revenue']),
        scenarioRevenue: _d(j['scenario_revenue']),
        notes: ((j['notes'] as List?) ?? const []).cast<String>(),
      );

  final double changePct;
  final double unitsChangePct;
  final double revenueChangePct;
  final double baselineRevenue;
  final double scenarioRevenue;
  final List<String> notes;
}

class AtRiskCustomer {
  const AtRiskCustomer({
    required this.customer,
    required this.probability,
    required this.recencyDays,
    required this.revenueLast365,
  });

  factory AtRiskCustomer.fromJson(Map<String, dynamic> j) => AtRiskCustomer(
        customer: j['customer'] as String,
        probability: _d(j['probability']),
        recencyDays: (j['recency_days'] as num).toInt(),
        revenueLast365: _d(j['revenue_last_365']),
      );

  final String customer;
  final double probability;
  final int recencyDays;
  final double revenueLast365;
}

class ChurnReport {
  const ChurnReport({
    required this.customersScored,
    required this.revenueAtRisk,
    required this.riskBands,
    required this.topAtRisk,
  });

  factory ChurnReport.fromJson(Map<String, dynamic> j) => ChurnReport(
        customersScored: (j['customers_scored'] as num).toInt(),
        revenueAtRisk: _d(j['revenue_at_risk']),
        riskBands: {for (final e in (j['risk_bands'] as Map).entries) e.key as String: (e.value as num).toInt()},
        topAtRisk: [for (final a in j['top_at_risk'] as List) AtRiskCustomer.fromJson(a as Map<String, dynamic>)],
      );

  final int customersScored;
  final double revenueAtRisk;
  final Map<String, int> riskBands;
  final List<AtRiskCustomer> topAtRisk;
}

class CustomerSegment {
  const CustomerSegment({
    required this.name,
    required this.customers,
    required this.revenueShare,
    required this.avgRecencyDays,
    required this.avgSpend,
  });

  factory CustomerSegment.fromJson(Map<String, dynamic> j) => CustomerSegment(
        name: j['name'] as String,
        customers: (j['customers'] as num).toInt(),
        revenueShare: _d(j['revenue_share']),
        avgRecencyDays: _d(j['avg_recency_days']),
        avgSpend: _d(j['avg_spend']),
      );

  final String name;
  final int customers;
  final double revenueShare;
  final double avgRecencyDays;
  final double avgSpend;
}

/// One thing the agent team did to reach an answer.
class AgentStep {
  const AgentStep({required this.agent, required this.summary, this.detail = ''});

  factory AgentStep.fromJson(Map<String, dynamic> j) => AgentStep(
        agent: j['agent'] as String,
        summary: j['summary'] as String,
        detail: j['detail'] as String? ?? '',
      );

  final String agent; // knowledge, sql or csv
  final String summary;
  final String detail;
}

class ChatReply {
  ChatReply({
    required this.answer,
    required this.followUps,
    required this.answerable,
    this.chartUrl,
    this.how,
    this.steps = const [],
    this.sources = const [],
    this.source = 'llm',
  });

  factory ChatReply.fromJson(Map<String, dynamic> j) => ChatReply(
        answer: j['answer'] as String,
        followUps: ((j['follow_ups'] as List?) ?? const []).cast<String>(),
        answerable: j['answerable'] as bool? ?? true,
        chartUrl: j['chart_url'] as String?,
        how: j['how'] as String?,
        source: j['source'] as String? ?? 'llm',
        steps: [
          for (final s in (j['steps'] as List? ?? const []))
            AgentStep.fromJson(s as Map<String, dynamic>)
        ],
        sources: [
          for (final s in (j['sources'] as List? ?? const []))
            (s as Map<String, dynamic>)['title'] as String
        ],
      );

  /// agent, llm, template, or offline (answered by rules, no AI key on the server).
  final String source;
  final List<AgentStep> steps;
  final List<String> sources;
  final String answer;
  final List<String> followUps;
  final bool answerable;
  final String? chartUrl;
  final String? how;
}

/// Months a PDF report can be made for (newest first) and the suggested one.
class ReportMonths {
  ReportMonths({required this.months, required this.defaultMonth});

  factory ReportMonths.fromJson(Map<String, dynamic> j) => ReportMonths(
        months: [
          for (final m in (j['months'] as List? ?? const []))
            (month: (m as Map)['month'] as String, label: m['label'] as String),
        ],
        defaultMonth: j['default'] as String,
      );

  final List<({String month, String label})> months;
  final String defaultMonth;
}

class Recommendation {
  Recommendation({required this.title, required this.detail, required this.impact});

  factory Recommendation.fromJson(Map<String, dynamic> j) => Recommendation(
        title: j['title'] as String,
        detail: j['detail'] as String,
        impact: j['impact'] as String,
      );

  final String title;
  final String detail;
  final String impact;
}
