import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/brand.dart';
import '../core/format.dart';
import '../core/theme.dart';
import '../data/models.dart';
import '../state/providers.dart';
import '../widgets/common.dart';
import '../widgets/dataset_gate.dart';
import '../widgets/visuals.dart';

const _horizons = [(30, '30 days'), (90, '90 days'), (365, '1 year')];
const _modelNames = {'prophet': 'Prophet', 'sarima': 'SARIMA', 'xgboost': 'XGBoost', 'trend': 'simple trend'};

class ForecastScreen extends ConsumerStatefulWidget {
  const ForecastScreen({super.key});

  @override
  ConsumerState<ForecastScreen> createState() => _ForecastScreenState();
}

class _ForecastScreenState extends ConsumerState<ForecastScreen> {
  String _target = 'revenue';
  int _horizon = 90;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: const Text('Forecast'),
          actions: const [Padding(padding: EdgeInsets.only(right: 12), child: DatasetChip())],
        ),
        body: DatasetGate(builder: (context, dataset) {
          final hasUnits = ref.watch(profileProvider(dataset.id)).value?.mapping['quantity'] != null;
          final targets = [('revenue', 'Revenue'), ('orders', 'Orders'), if (hasUnits) ('quantity', 'Units sold')];
          if (!targets.any((t) => t.$1 == _target)) _target = 'revenue';
          final key = (datasetId: dataset.id, target: _target, horizonDays: _horizon);
          final result = ref.watch(forecastProvider(key));
          return RefreshIndicator(
            onRefresh: () async => ref.invalidate(forecastProvider(key)),
            child: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 32), children: [
              DropdownButtonFormField<String>(
                initialValue: _target,
                decoration: const InputDecoration(labelText: 'Metric', prefixIcon: Icon(Icons.analytics_outlined)),
                items: [for (final (v, l) in targets) DropdownMenuItem(value: v, child: Text(l))],
                onChanged: (v) => setState(() => _target = v ?? 'revenue'),
              ),
              const SizedBox(height: 12),
              SegmentedButton<int>(
                showSelectedIcon: false,
                segments: [for (final (v, l) in _horizons) ButtonSegment(value: v, label: Text(l))],
                selected: {_horizon},
                onSelectionChanged: (s) => setState(() => _horizon = s.first),
              ),
              const SizedBox(height: 16),
              ...result.when(
                loading: () => const [_TrainingCard()],
                error: (e, _) => [
                  AppCard(child: InlineError('$e', onRetry: () => ref.invalidate(forecastProvider(key)))),
                ],
                data: (r) => [
                  _TotalCard(result: r),
                  const SizedBox(height: 12),
                  if (r.chartUrl != null)
                    AppCard(child: ChartImage(r.chartUrl!, title: '${r.targetLabel} forecast', semanticLabel: '${r.targetLabel} forecast')),
                  const SizedBox(height: 12),
                  _AccuracyCard(result: r),
                  if (r.target == 'revenue') ...[
                    const SizedBox(height: 20),
                    _WhatIfCard(datasetId: dataset.id, currency: dataset.currency),
                  ],
                ],
              ),
            ]),
          );
        }),
      );
}

class _TrainingCard extends StatelessWidget {
  const _TrainingCard();

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Column(children: [
      AppCard(
        child: Row(children: [
          const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.4)),
          const SizedBox(width: 14),
          Expanded(
            child: Text('Testing three forecasting models on your history and picking the most accurate. '
                'This takes about 10-20 seconds.', style: TextStyle(color: p.muted)),
          ),
        ]),
      ),
      const SizedBox(height: 12),
      const SkeletonCard(),
    ]);
  }
}

class _TotalCard extends StatelessWidget {
  const _TotalCard({required this.result});

  final ForecastResult result;

  String _fmt(double v) =>
      result.target == 'revenue' ? money(v, result.currency) : compactNumber(v);

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    const onAccent = Colors.white;
    final soft = Colors.white.withValues(alpha: 0.8);
    final span = _horizons.firstWhere((h) => h.$1 == result.horizonDays, orElse: () => (0, '${result.horizonDays} days')).$2;
    final change = result.changePct;
    return GradientCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          const Icon(Icons.insights_rounded, color: onAccent, size: 18),
          const SizedBox(width: 6),
          Expanded(
            child: Text('Predicted ${result.targetLabel.toLowerCase()}, next $span',
                style: t.labelLarge?.copyWith(color: soft, fontWeight: FontWeight.w600)),
          ),
        ]),
        const SizedBox(height: 8),
        FittedBox(
          fit: BoxFit.scaleDown,
          alignment: Alignment.centerLeft,
          child: CountUpText(
            value: result.total,
            format: _fmt,
            finalText: _fmt(result.total),
            style: t.displaySmall?.copyWith(fontWeight: FontWeight.w800, color: onAccent, letterSpacing: -1),
          ),
        ),
        const SizedBox(height: 10),
        if (change != null)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
            decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.18), borderRadius: BorderRadius.circular(20)),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(change >= 0 ? Icons.arrow_upward_rounded : Icons.arrow_downward_rounded, size: 15, color: onAccent),
              const SizedBox(width: 3),
              Text(signedPct(change).replaceFirst(RegExp(r'^[+-]'), ''),
                  style: t.labelMedium?.copyWith(color: onAccent, fontWeight: FontWeight.w800)),
              Flexible(child: Text(' vs the previous $span', style: t.labelMedium?.copyWith(color: soft))),
            ]),
          ),
        const SizedBox(height: 18),
        Semantics(
          container: true,
          label: 'Likely between ${_fmt(result.totalLower)} and ${_fmt(result.totalUpper)}',
          excludeSemantics: true,
          child: RangeBar(
            low: result.totalLower,
            mid: result.total,
            high: result.totalUpper,
            format: _fmt,
            onGradient: true,
          ),
        ),
        if (result.message != null) ...[
          const SizedBox(height: 14),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(12)),
            child: Row(children: [
              const Icon(Icons.info_outline, color: onAccent),
              const SizedBox(width: 10),
              Expanded(child: Text(result.message!, style: t.bodyMedium?.copyWith(color: onAccent))),
            ]),
          ),
        ],
      ]),
    );
  }
}

class _AccuracyCard extends StatelessWidget {
  const _AccuracyCard({required this.result});

  final ForecastResult result;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    return AppCard(
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        IconBadge(icon: Icons.verified_outlined, color: p.forecast),
        const SizedBox(width: 12),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Model accuracy', style: t.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
            const SizedBox(height: 2),
            Text(result.accuracyNote, style: t.bodyMedium),
            const SizedBox(height: 2),
            Text('Best model on your data: ${_modelNames[result.model] ?? result.model}',
                style: t.bodySmall?.copyWith(color: p.muted)),
          ]),
        ),
      ]),
    );
  }
}

class _WhatIfCard extends ConsumerStatefulWidget {
  const _WhatIfCard({required this.datasetId, this.currency});

  final String datasetId;
  final String? currency;

  @override
  ConsumerState<_WhatIfCard> createState() => _WhatIfCardState();
}

class _WhatIfCardState extends ConsumerState<_WhatIfCard> {
  double _slider = 0;
  int _applied = 0;

  static const _presets = [-10, -5, 0, 5, 10];

  void _apply(int pct) {
    HapticFeedback.selectionClick();
    setState(() {
      _slider = pct.toDouble();
      _applied = pct;
    });
  }

  String _signed(num v) => '${v > 0 ? '+' : ''}${v.round()}%';

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    final key = (datasetId: widget.datasetId, changePct: _applied);
    final result = _applied == 0 ? null : ref.watch(whatIfProvider(key));
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          IconBadge(icon: Icons.tune_rounded, color: Brand.violet),
          const SizedBox(width: 10),
          Expanded(
            child: Text('What if I change prices?', style: t.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
          ),
        ]),
        const SizedBox(height: 4),
        Text('Pick a change or drag the slider to see the estimated effect over the next month.',
            style: t.bodySmall?.copyWith(color: p.muted)),
        const SizedBox(height: 12),
        SizedBox(
          width: double.infinity,
          child: SegmentedButton<int>(
            showSelectedIcon: false,
            emptySelectionAllowed: true,
            style: SegmentedButton.styleFrom(padding: EdgeInsets.zero, visualDensity: VisualDensity.compact),
            segments: [
              for (final pct in _presets)
                ButtonSegment(
                  value: pct,
                  label: FittedBox(fit: BoxFit.scaleDown, child: Text(_signed(pct))),
                  tooltip: pct == 0 ? 'Prices as they are' : 'Price ${_signed(pct)}',
                ),
            ],
            selected: {if (_presets.contains(_slider.round()) && _applied == _slider.round()) _applied},
            onSelectionChanged: (s) => _apply(s.isEmpty ? 0 : s.first),
          ),
        ),
        Slider(
          value: _slider,
          min: -10,
          max: 10,
          divisions: 20,
          label: _signed(_slider),
          semanticFormatterCallback: (v) => 'Price change ${v.round()} percent',
          onChanged: (v) {
            if (v.round() != _slider.round()) HapticFeedback.selectionClick();
            setState(() => _slider = v);
          },
          onChangeEnd: (v) => setState(() => _applied = v.round()),
        ),
        Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
          Text('-10%', style: t.labelSmall?.copyWith(color: p.muted)),
          Text('Price ${_signed(_slider)}', style: t.labelLarge?.copyWith(fontWeight: FontWeight.w700)),
          Text('+10%', style: t.labelSmall?.copyWith(color: p.muted)),
        ]),
        const SizedBox(height: 12),
        if (result == null)
          Text('Prices as they are today.', style: t.bodyMedium?.copyWith(color: p.muted))
        else
          result.when(
            loading: () => const Skeleton(height: 48),
            error: (e, _) => InlineError('$e', onRetry: () => ref.invalidate(whatIfProvider(key))),
            data: (w) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Expanded(child: _Effect(label: 'Revenue', pct: w.revenueChangePct)),
                const SizedBox(width: 12),
                Expanded(child: _Effect(label: 'Units sold', pct: w.unitsChangePct)),
              ]),
              const SizedBox(height: 10),
              Text(
                'Monthly revenue: ${money(w.baselineRevenue, widget.currency)} \u2192 '
                '${money(w.scenarioRevenue, widget.currency)}',
                style: t.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 4),
              for (final note in w.notes)
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Icon(Icons.info_outline, size: 16, color: p.muted),
                    const SizedBox(width: 6),
                    Expanded(child: Text(note, style: t.bodySmall?.copyWith(color: p.muted))),
                  ]),
                ),
            ]),
          ),
      ]),
    );
  }
}

class _Effect extends StatelessWidget {
  const _Effect({required this.label, required this.pct});

  final String label;
  final double pct;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    final color = pct.abs() < 0.5 ? p.muted : (pct > 0 ? p.positive : p.negative);
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(border: Border.all(color: p.border), borderRadius: BorderRadius.circular(14)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: t.labelMedium?.copyWith(color: p.muted)),
        const SizedBox(height: 4),
        Text(signedPct(pct), style: t.titleLarge?.copyWith(fontWeight: FontWeight.w800, color: color)),
      ]),
    );
  }
}
