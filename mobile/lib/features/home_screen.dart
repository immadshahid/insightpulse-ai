import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/brand.dart';
import '../core/format.dart';
import '../core/share.dart';
import '../core/theme.dart';
import '../data/models.dart';
import '../state/providers.dart';
import '../widgets/common.dart';
import '../widgets/dataset_gate.dart';
import '../widgets/motion.dart';
import '../widgets/visuals.dart';
import 'customers_screen.dart';
import 'report_screen.dart';

const periods = [('7d', '7D'), ('30d', '30D'), ('90d', '90D'), ('1y', '1Y')];

class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(authProvider);
    return Scaffold(
      body: DatasetGate(
        builder: (context, dataset) {
          final period = ref.watch(periodProvider);
          final key = (datasetId: dataset.id, period: period);
          final dash = ref.watch(dashboardProvider(key));
          return RefreshIndicator(
            onRefresh: () async {
              ref.invalidate(dashboardProvider(key));
              ref.invalidate(recommendationsProvider(dataset.id));
            },
            child: ListView(
              padding: const EdgeInsets.only(bottom: 32),
              children: [
                _HomeHero(
                  name: session?.firstName ?? '',
                  dataset: dataset,
                  period: period,
                  onPeriod: (v) {
                    HapticFeedback.selectionClick();
                    ref.read(periodProvider.notifier).set(v);
                  },
                  summary: dash.when(
                    skipLoadingOnReload: true,
                    loading: () => const _GlassSkeleton(),
                    error: (_, _) => const SizedBox.shrink(),
                    data: (d) => FadeSlideIn(child: _SummaryCard(dashboard: d)),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: dash.when(
                      skipLoadingOnReload: true,
                      loading: () => const [_DashboardSkeleton()],
                      error: (e, _) => [
                        SizedBox(
                          height: 360,
                          child: ErrorState(error: e, onRetry: () => ref.invalidate(dashboardProvider(key))),
                        ),
                      ],
                      data: (d) => _content(context, ref, d, dataset),
                    ),
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }

  List<Widget> _content(BuildContext context, WidgetRef ref, Dashboard d, DatasetSummary dataset) {
    final p = context.palette;
    final w = d.window;
    return [
      FadeSlideIn(child: _QuickActions(dataset: dataset)),
      const SizedBox(height: 20),
      FadeSlideIn(
        index: 1,
        child: SectionTitle(
          'Key numbers',
          trailing: Text(
            w == null
                ? 'vs ${previousPeriodLabel(d.period)}'
                : w.previousComplete
                    ? 'vs ${dateRange(w.prevStart, w.prevEnd)}'
                    : 'Not enough history to compare',
            style: Theme.of(context).textTheme.labelMedium?.copyWith(color: p.muted),
          ),
        ),
      ),
      FadeSlideIn(index: 2, child: _KpiGrid(dashboard: d)),
      const SizedBox(height: 12),
      FadeSlideIn(index: 3, child: _GoalCard(dashboard: d)),
      const SizedBox(height: 12),
      FadeSlideIn(index: 3, child: _CustomersLink(dataset: dataset)),
      const SizedBox(height: 12),
      FadeSlideIn(index: 3, child: _ReportBanner(dataset: dataset)),
      const SizedBox(height: 16),
      if (d.trendChartUrl != null)
        FadeSlideIn(
          index: 3,
          child: AppCard(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Revenue trend',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
              const SizedBox(height: 12),
              ChartImage(d.trendChartUrl!, title: 'Revenue trend', semanticLabel: 'Revenue trend with forecast'),
              const SizedBox(height: 10),
              _ForecastFootnote(dashboard: d),
            ]),
          ),
        ),
      const SizedBox(height: 20),
      FadeSlideIn(index: 4, child: _Recommendations(datasetId: dataset.id)),
    ];
  }
}

/// "15M" / "500k" / "12,000" to a number.
double? parseAmount(String text) {
  final s = text.trim().toLowerCase().replaceAll(',', '');
  if (s.isEmpty) return null;
  final factor = s.endsWith('m') ? 1e6 : (s.endsWith('k') ? 1e3 : 1.0);
  final value = double.tryParse(factor == 1 ? s : s.substring(0, s.length - 1));
  return value == null || value <= 0 ? null : value * factor;
}

class _GoalCard extends ConsumerWidget {
  const _GoalCard({required this.dashboard});

  final Dashboard dashboard;

  Future<void> _edit(BuildContext context, WidgetRef ref, double? current) async {
    HapticFeedback.selectionClick();
    final result = await showDialog<({double? goal})>(
      context: context,
      useRootNavigator: true,
      builder: (_) => _GoalDialog(current: current, currency: dashboard.currency),
    );
    if (result != null) ref.read(goalsProvider.notifier).set(dashboard.period, result.goal);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    final goal = ref.watch(goalsProvider)[dashboard.period];
    if (goal == null) {
      return AppCard(
        onTap: () => _edit(context, ref, null),
        child: Row(children: [
          IconBadge(icon: Icons.flag_outlined, color: p.positive),
          const SizedBox(width: 12),
          Expanded(
            child: Text('Set a revenue goal for this period',
                style: t.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
          ),
          Icon(Icons.add_rounded, color: p.muted),
        ]),
      );
    }
    final revenue = dashboard.kpis.where((k) => k.key == 'revenue').firstOrNull?.value ?? 0;
    final pct = revenue / goal * 100;
    final reached = pct >= 100;
    final color = reached ? p.positive : p.accent;
    return AppCard(
      onTap: () => _edit(context, ref, goal),
      child: Row(children: [
        Semantics(
          label: 'Revenue goal ${pct.round()} percent reached',
          excludeSemantics: true,
          child: RingGauge(
            value: pct.clamp(0, 100).toDouble(),
            color: color,
            size: 72,
            child: Text('${pct.round()}%', style: t.titleSmall?.copyWith(fontWeight: FontWeight.w800)),
          ),
        ),
        const SizedBox(width: 14),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Revenue goal', style: t.labelLarge?.copyWith(color: p.muted, fontWeight: FontWeight.w600)),
            const SizedBox(height: 2),
            Text(
              '${money(revenue, dashboard.currency)} of ${money(goal, dashboard.currency)}',
              style: t.titleSmall?.copyWith(fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: 2),
            Text(
              reached ? 'Goal reached' : '${money(goal - revenue, dashboard.currency)} to go',
              style: t.bodySmall?.copyWith(color: reached ? p.positive : p.muted),
            ),
          ]),
        ),
        Icon(Icons.edit_outlined, size: 18, color: p.muted),
      ]),
    );
  }
}

class _GoalDialog extends StatefulWidget {
  const _GoalDialog({this.current, this.currency});

  final double? current;
  final String? currency;

  @override
  State<_GoalDialog> createState() => _GoalDialogState();
}

class _GoalDialogState extends State<_GoalDialog> {
  late final _input = TextEditingController(text: widget.current?.toStringAsFixed(0) ?? '');
  String? _error;

  @override
  void dispose() {
    _input.dispose();
    super.dispose();
  }

  void _save() {
    final value = parseAmount(_input.text);
    if (value == null) {
      setState(() => _error = 'Enter an amount, like 15M or 500000');
      return;
    }
    Navigator.of(context).pop((goal: value));
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: const Text('Revenue goal'),
        content: TextField(
          controller: _input,
          autofocus: true,
          onSubmitted: (_) => _save(),
          decoration: InputDecoration(
            labelText: 'Goal for this period',
            prefixText: widget.currency == null ? null : '${widget.currency} ',
            errorText: _error,
          ),
        ),
        actions: [
          if (widget.current != null)
            TextButton(onPressed: () => Navigator.of(context).pop((goal: null)), child: const Text('Remove')),
          TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Cancel')),
          FilledButton(onPressed: _save, child: const Text('Save')),
        ],
      );
}

class _CustomersLink extends StatelessWidget {
  const _CustomersLink({required this.dataset});

  final DatasetSummary dataset;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    return AppCard(
      onTap: () {
        HapticFeedback.selectionClick();
        Navigator.of(context, rootNavigator: true).push(MaterialPageRoute<void>(
          builder: (_) => CustomersScreen(datasetId: dataset.id, currency: dataset.currency),
        ));
      },
      child: Row(children: [
        IconBadge(icon: Icons.groups_outlined, color: Brand.tint('customers', Theme.of(context).brightness)),
        const SizedBox(width: 12),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Your customers', style: t.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
            Text('Who is loyal, and who may be leaving', style: t.bodySmall?.copyWith(color: p.muted)),
          ]),
        ),
        Icon(Icons.chevron_right_rounded, color: p.muted),
      ]),
    );
  }
}

/// Full-width gradient header: greeting, data freshness, period pills and the summary.
class _HomeHero extends StatelessWidget {
  const _HomeHero({
    required this.name,
    required this.dataset,
    required this.period,
    required this.onPeriod,
    required this.summary,
  });

  final String name;
  final DatasetSummary dataset;
  final String period;
  final ValueChanged<String> onPeriod;
  final Widget summary;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final top = MediaQuery.paddingOf(context).top;
    final soft = Colors.white.withValues(alpha: 0.82);
    return Container(
      decoration: BoxDecoration(
        gradient: Brand.hero(Theme.of(context).brightness),
        borderRadius: const BorderRadius.vertical(bottom: Radius.circular(32)),
      ),
      child: Stack(children: [
        // Soft light shapes for depth.
        Positioned(right: -60, top: -40, child: _Glow(size: 200)),
        Positioned(left: -50, bottom: 60, child: _Glow(size: 140)),
        Padding(
          padding: EdgeInsets.fromLTRB(16, top + 10, 16, 18),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              _Avatar(name: name),
              const SizedBox(width: 12),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(greeting(DateTime.now()), style: t.bodyMedium?.copyWith(color: soft)),
                  Text(
                    name,
                    overflow: TextOverflow.ellipsis,
                    style: t.headlineSmall?.copyWith(color: Colors.white, fontWeight: FontWeight.w800),
                  ),
                ]),
              ),
              const _AccountMenu(color: Colors.white),
            ]),
            const SizedBox(height: 14),
            const Align(alignment: Alignment.centerLeft, child: DatasetChip()),
            if (dataset.dateMax != null) ...[
              const SizedBox(height: 8),
              _Freshness(dataset: dataset, color: soft),
            ],
            const SizedBox(height: 14),
            _PeriodPills(selected: period, onSelected: onPeriod),
            const SizedBox(height: 16),
            summary,
          ]),
        ),
      ]),
    );
  }
}

class _Glow extends StatelessWidget {
  const _Glow({required this.size});

  final double size;

  @override
  Widget build(BuildContext context) => IgnorePointer(
        child: Container(
          width: size,
          height: size,
          decoration: BoxDecoration(shape: BoxShape.circle, color: Colors.white.withValues(alpha: 0.07)),
        ),
      );
}

class _Avatar extends StatelessWidget {
  const _Avatar({required this.name});

  final String name;

  @override
  Widget build(BuildContext context) => Container(
        width: 46,
        height: 46,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: Colors.white.withValues(alpha: 0.2),
          border: Border.all(color: Colors.white.withValues(alpha: 0.45), width: 1.5),
        ),
        child: Text(
          name.isEmpty ? '?' : name[0].toUpperCase(),
          style: Theme.of(context).textTheme.titleMedium?.copyWith(color: Colors.white, fontWeight: FontWeight.w800),
        ),
      );
}

/// Frosted period selector for the gradient header.
class _PeriodPills extends StatelessWidget {
  const _PeriodPills({required this.selected, required this.onSelected});

  final String selected;
  final ValueChanged<String> onSelected;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.16),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.white.withValues(alpha: 0.22)),
      ),
      child: Row(children: [
        for (final (v, l) in periods)
          Expanded(
            child: Semantics(
              button: true,
              selected: v == selected,
              child: GestureDetector(
                behavior: HitTestBehavior.opaque,
                onTap: () => onSelected(v),
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 220),
                  curve: Curves.easeOutCubic,
                  constraints: const BoxConstraints(minHeight: kMinTouch - 4),
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    color: v == selected ? Colors.white : Colors.transparent,
                    borderRadius: BorderRadius.circular(12),
                    boxShadow: v == selected
                        ? [BoxShadow(color: Colors.black.withValues(alpha: 0.12), blurRadius: 10, offset: const Offset(0, 3))]
                        : null,
                  ),
                  child: Text(
                    l,
                    style: t.labelLarge?.copyWith(
                      fontWeight: FontWeight.w800,
                      color: v == selected ? Brand.indigo : Colors.white,
                    ),
                  ),
                ),
              ),
            ),
          ),
      ]),
    );
  }
}

class _GlassSkeleton extends StatelessWidget {
  const _GlassSkeleton();

  @override
  Widget build(BuildContext context) => Container(
        height: 150,
        decoration: BoxDecoration(
          color: Colors.white.withValues(alpha: 0.14),
          borderRadius: BorderRadius.circular(kRadius + 4),
        ),
      );
}

/// Colourful shortcuts to the most-used places.
class _QuickActions extends StatelessWidget {
  const _QuickActions({required this.dataset});

  final DatasetSummary dataset;

  @override
  Widget build(BuildContext context) {
    void push(Widget screen) {
      HapticFeedback.selectionClick();
      Navigator.of(context, rootNavigator: true).push(MaterialPageRoute<void>(builder: (_) => screen));
    }

    final actions = [
      (Icons.auto_awesome, 'Ask AI', const [Color(0xFF6366F1), Color(0xFF8B5CF6)], () => context.go('/ask')),
      (Icons.auto_graph_rounded, 'Forecast', const [Color(0xFF0EA5E9), Color(0xFF06B6D4)], () => context.go('/forecast')),
      (
        Icons.groups_rounded,
        'Customers',
        const [Color(0xFFEC4899), Color(0xFFF43F5E)],
        () => push(CustomersScreen(datasetId: dataset.id, currency: dataset.currency)),
      ),
      (
        Icons.picture_as_pdf_rounded,
        'Report',
        const [Color(0xFFF59E0B), Color(0xFFF97316)],
        () => push(ReportScreen(datasetId: dataset.id, datasetName: dataset.name)),
      ),
    ];
    final t = Theme.of(context).textTheme;
    return Row(children: [
      for (final (icon, label, colors, onTap) in actions)
        Expanded(
          child: Semantics(
            button: true,
            label: 'Open $label',
            excludeSemantics: true,
            child: InkWell(
              borderRadius: BorderRadius.circular(18),
              onTap: onTap,
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Column(children: [
                  Container(
                    width: 56,
                    height: 56,
                    decoration: BoxDecoration(
                      gradient: LinearGradient(colors: colors, begin: Alignment.topLeft, end: Alignment.bottomRight),
                      borderRadius: BorderRadius.circular(18),
                      boxShadow: [
                        BoxShadow(color: colors.last.withValues(alpha: 0.35), blurRadius: 14, offset: const Offset(0, 6)),
                      ],
                    ),
                    child: Icon(icon, color: Colors.white, size: 26),
                  ),
                  const SizedBox(height: 8),
                  FittedBox(
                    fit: BoxFit.scaleDown,
                    child: Text(label, style: t.labelLarge?.copyWith(fontWeight: FontWeight.w700)),
                  ),
                ]),
              ),
            ),
          ),
        ),
    ]);
  }
}

/// Eye-catching entry point for the monthly PDF.
class _ReportBanner extends StatelessWidget {
  const _ReportBanner({required this.dataset});

  final DatasetSummary dataset;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    void open() {
      HapticFeedback.selectionClick();
      Navigator.of(context, rootNavigator: true).push(MaterialPageRoute<void>(
        builder: (_) => ReportScreen(datasetId: dataset.id, datasetName: dataset.name),
      ));
    }

    final radius = BorderRadius.circular(kRadius + 4);
    // Gradient and shadow on a DecoratedBox, ripple on a transparent Material inside it,
    // so the rounded corners stay clean.
    return DecoratedBox(
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          colors: [Color(0xFFF97316), Color(0xFFDB2777)],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: radius,
        boxShadow: [
          BoxShadow(color: const Color(0xFFDB2777).withValues(alpha: 0.3), blurRadius: 18, offset: const Offset(0, 8)),
        ],
      ),
      child: Material(
        type: MaterialType.transparency,
        borderRadius: radius,
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: open,
          child: Padding(
            padding: const EdgeInsets.all(18),
            child: Row(children: [
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Colors.white.withValues(alpha: 0.2),
                borderRadius: BorderRadius.circular(16),
              ),
              child: const Icon(Icons.picture_as_pdf_outlined, color: Colors.white, size: 28),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Monthly PDF report',
                    style: t.titleMedium?.copyWith(color: Colors.white, fontWeight: FontWeight.w800)),
                const SizedBox(height: 2),
                Text('Charts, data overview and forecast for any month',
                    style: t.bodySmall?.copyWith(color: Colors.white.withValues(alpha: 0.9))),
              ]),
            ),
            const Icon(Icons.arrow_forward_rounded, color: Colors.white),
          ]),
          ),
        ),
      ),
    );
  }
}

class _AccountMenu extends ConsumerWidget {
  const _AccountMenu({this.color});

  final Color? color;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final mode = ref.watch(themeModeProvider);
    final isDark = mode == ThemeMode.dark ||
        (mode == ThemeMode.system && MediaQuery.platformBrightnessOf(context) == Brightness.dark);
    return Row(mainAxisSize: MainAxisSize.min, children: [
      IconButton(
        color: color,
        tooltip: isDark ? 'Light mode' : 'Dark mode',
        icon: Icon(isDark ? Icons.light_mode_outlined : Icons.dark_mode_outlined),
        onPressed: () => ref.read(themeModeProvider.notifier).set(isDark ? ThemeMode.light : ThemeMode.dark),
      ),
      IconButton(
        color: color,
        tooltip: 'Sign out',
        icon: const Icon(Icons.logout_rounded),
        onPressed: () => ref.read(authProvider.notifier).logout(),
      ),
    ]);
  }
}

class _SummaryCard extends ConsumerWidget {
  const _SummaryCard({required this.dashboard});

  final Dashboard dashboard;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = Theme.of(context).textTheme;
    const onAccent = Colors.white;
    final pending = dashboard.summaryStatus == 'pending';
    // Frosted glass card that sits on the gradient header.
    return Container(
      padding: const EdgeInsets.fromLTRB(18, 14, 8, 12),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.14),
        borderRadius: BorderRadius.circular(kRadius + 4),
        border: Border.all(color: Colors.white.withValues(alpha: 0.24)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.18),
              borderRadius: BorderRadius.circular(20),
            ),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              const Icon(Icons.auto_awesome, color: onAccent, size: 15),
              const SizedBox(width: 6),
              Text(dashboard.summarySource == 'llm' ? 'AI summary' : 'Summary',
                  style: t.labelMedium?.copyWith(color: onAccent, fontWeight: FontWeight.w700)),
            ]),
          ),
          const SizedBox(width: 8),
          if (pending)
            Expanded(
              child: Text('Writing AI summary...',
                  overflow: TextOverflow.ellipsis,
                  style: t.labelSmall?.copyWith(color: onAccent.withValues(alpha: 0.85))),
            )
          else
            const Spacer(),
          IconButton(
            tooltip: 'Share summary',
            color: onAccent,
            icon: const Icon(Icons.ios_share_rounded, size: 20),
            onPressed: () {
              HapticFeedback.selectionClick();
              ref.read(sharerProvider)(withSignature(dashboard.summary), subject: 'Business summary');
            },
          ),
        ]),
        const SizedBox(height: 6),
        Padding(
          padding: const EdgeInsets.only(right: 10),
          child: Text(dashboard.summary,
              style: t.bodyLarge?.copyWith(color: onAccent, height: 1.45, fontWeight: FontWeight.w500)),
        ),
        const SizedBox(height: 8),
        TextButton.icon(
          style: TextButton.styleFrom(
            foregroundColor: Brand.indigo,
            backgroundColor: Colors.white,
            padding: const EdgeInsets.symmetric(horizontal: 16),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
          ),
          onPressed: () => context.go('/insights'),
          icon: const Text('See why', style: TextStyle(fontWeight: FontWeight.w700)),
          label: const Icon(Icons.arrow_forward_rounded, size: 18),
        ),
      ]),
    );
  }
}

/// "Data through 31 Oct 2026 - 28.2K records".
class _Freshness extends StatelessWidget {
  const _Freshness({required this.dataset, this.color});

  final DatasetSummary dataset;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final c = color ?? context.palette.muted;
    final end = DateTime.tryParse(dataset.dateMax ?? '');
    if (end == null) return const SizedBox.shrink();
    return Row(children: [
      Icon(Icons.update_rounded, size: 14, color: c),
      const SizedBox(width: 4),
      Flexible(
        child: Text(
          'Data through ${shortDate(end)} \u00b7 ${compactNumber(dataset.rowCount)} records',
          style: Theme.of(context).textTheme.labelMedium?.copyWith(color: c),
        ),
      ),
    ]);
  }
}

class _KpiGrid extends StatelessWidget {
  const _KpiGrid({required this.dashboard});

  final Dashboard dashboard;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, c) {
      final w = (c.maxWidth - 12) / 2;
      return Wrap(spacing: 12, runSpacing: 12, children: [
        for (final k in dashboard.kpis)
          SizedBox(
            width: w,
            child: _KpiTile(kpi: k, currency: dashboard.currency, onTap: () => _showDetails(context, k)),
          ),
      ]);
    });
  }

  void _showDetails(BuildContext context, KpiCard kpi) {
    HapticFeedback.selectionClick();
    showModalBottomSheet<void>(
      useRootNavigator: true,
      context: context,
      showDragHandle: true,
      builder: (_) => _KpiDetails(kpi: kpi, dashboard: dashboard),
    );
  }
}

const _kpiMeaning = {
  'revenue': 'Total money received from sales in the period, after discounts.',
  'orders': 'Number of separate orders placed (one order can contain several products).',
  'avg_order_value': 'Revenue divided by orders: how much a typical order is worth.',
  'active_customers': 'Different customers who bought at least once in the period.',
};

class _KpiDetails extends StatelessWidget {
  const _KpiDetails({required this.kpi, required this.dashboard});

  final KpiCard kpi;
  final Dashboard dashboard;

  String _fmt(double v) => kpi.isMoney ? money(v, dashboard.currency) : compactNumber(v);

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    final w = dashboard.window;
    Widget row(String label, String value, {String? caption}) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(label, style: t.bodyMedium?.copyWith(color: p.muted)),
                if (caption != null) Text(caption, style: t.labelSmall?.copyWith(color: p.muted)),
              ]),
            ),
            Text(value, style: t.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
          ]),
        );
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            IconBadge(
              icon: _KpiTile.icons[kpi.key] ?? Icons.analytics_outlined,
              color: Brand.tint(kpi.key, Theme.of(context).brightness),
            ),
            const SizedBox(width: 10),
            Expanded(child: Text(kpi.label, style: t.titleLarge?.copyWith(fontWeight: FontWeight.w800))),
          ]),
          const SizedBox(height: 8),
          Text(_kpiMeaning[kpi.key] ?? '', style: t.bodyMedium?.copyWith(color: p.muted)),
          if (kpi.spark.length > 1) ...[
            const SizedBox(height: 14),
            Sparkline(values: kpi.spark, color: Brand.tint(kpi.key, Theme.of(context).brightness), height: 64),
          ],
          const SizedBox(height: 12),
          row('This period', kpi.display, caption: w == null ? null : dateRange(w.start, w.end)),
          const Divider(height: 1),
          row('Previous period', kpi.previous == null ? 'No data' : _fmt(kpi.previous!),
              caption: w == null ? null : dateRange(w.prevStart, w.prevEnd)),
          const Divider(height: 1),
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Row(children: [
              Expanded(child: Text('Change', style: t.bodyMedium?.copyWith(color: p.muted))),
              DeltaPill(changePct: kpi.changePct),
            ]),
          ),
        ]),
      ),
    );
  }
}

class _KpiTile extends StatelessWidget {
  const _KpiTile({required this.kpi, required this.currency, this.onTap});

  final KpiCard kpi;
  final String? currency;
  final VoidCallback? onTap;

  static const icons = {
    'revenue': Icons.payments_outlined,
    'orders': Icons.receipt_long_outlined,
    'avg_order_value': Icons.shopping_basket_outlined,
    'active_customers': Icons.people_outline,
  };

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    final tint = Brand.tint(kpi.key, Theme.of(context).brightness);
    return AppCard(
      padding: const EdgeInsets.fromLTRB(14, 14, 14, 12),
      onTap: onTap,
      child: Semantics(
        button: onTap != null,
        label: '${kpi.label} ${kpi.display}, '
            '${kpi.changePct == null ? 'no earlier data' : '${signedPct(kpi.changePct!)} versus previous period'}'
            '. Show details',
        excludeSemantics: true,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Container(
              width: 32,
              height: 32,
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  colors: [tint, Color.lerp(tint, Colors.white, 0.25)!],
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                ),
                borderRadius: BorderRadius.circular(10),
                boxShadow: [BoxShadow(color: tint.withValues(alpha: 0.3), blurRadius: 8, offset: const Offset(0, 3))],
              ),
              child: Icon(icons[kpi.key] ?? Icons.analytics_outlined, color: Colors.white, size: 18),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: FittedBox(
                fit: BoxFit.scaleDown,
                alignment: Alignment.centerLeft,
                child: Text(kpi.label, style: t.labelLarge?.copyWith(color: p.muted, fontWeight: FontWeight.w600)),
              ),
            ),
          ]),
          const SizedBox(height: 10),
          FittedBox(
            fit: BoxFit.scaleDown,
            alignment: Alignment.centerLeft,
            child: CountUpText(
              value: kpi.value,
              finalText: kpi.display,
              format: (v) => kpi.isMoney ? money(v, currency) : compactNumber(v.round()),
              style: t.headlineSmall?.copyWith(fontWeight: FontWeight.w800, letterSpacing: -0.5),
            ),
          ),
          const SizedBox(height: 6),
          Sparkline(values: kpi.spark, color: tint, height: 30),
          const SizedBox(height: 8),
          DeltaPill(changePct: kpi.changePct),
        ]),
      ),
    );
  }
}

class _ForecastFootnote extends StatelessWidget {
  const _ForecastFootnote({required this.dashboard});

  final Dashboard dashboard;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final style = Theme.of(context).textTheme.bodySmall?.copyWith(color: p.muted);
    final (icon, text) = switch (dashboard.forecastStatus) {
      'ready' => (Icons.verified_outlined, 'Forecast: ${dashboard.forecastNote ?? ''}'),
      'pending' => (Icons.hourglass_top_rounded, 'Building your forecast... it will appear here shortly.'),
      'failed' => (Icons.error_outline, 'The forecast could not be built for this data.'),
      _ => (Icons.info_outline, 'Forecasts need at least 2 weeks of data.'),
    };
    return Row(children: [
      Icon(icon, size: 16, color: dashboard.forecastStatus == 'ready' ? p.forecast : p.muted),
      const SizedBox(width: 6),
      Expanded(child: Text(text, style: style)),
    ]);
  }
}

class _Recommendations extends ConsumerWidget {
  const _Recommendations({required this.datasetId});

  final String datasetId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final recs = ref.watch(recommendationsProvider(datasetId));
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      const SectionTitle('What to do next'),
      ...recs.when(
        loading: () => const [SkeletonCard(chart: false)],
        error: (e, _) => [AppCard(child: InlineError('$e', onRetry: () => ref.invalidate(recommendationsProvider(datasetId))))],
        data: (list) => [
          for (final (i, r) in list.indexed) ...[
            if (i > 0) const SizedBox(height: 10),
            AppCard(
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Container(
                  width: 32,
                  height: 32,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(gradient: Brand.hero(Theme.of(context).brightness), shape: BoxShape.circle),
                  child: Text('${i + 1}', style: t.labelLarge?.copyWith(color: Colors.white, fontWeight: FontWeight.w800)),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(r.title, style: t.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
                    const SizedBox(height: 6),
                    Pill(
                      '${r.impact[0].toUpperCase()}${r.impact.substring(1)} impact',
                      color: r.impact == 'high' ? p.negative : p.muted,
                      background: r.impact == 'high' ? p.warningSurface : p.border,
                    ),
                    const SizedBox(height: 6),
                    Text(r.detail, style: t.bodyMedium?.copyWith(color: p.muted)),
                  ]),
                ),
              ]),
            ),
          ],
        ],
      ),
    ]);
  }
}

class _DashboardSkeleton extends StatelessWidget {
  const _DashboardSkeleton();

  @override
  Widget build(BuildContext context) => Column(children: [
        const Skeleton(height: 160, radius: kRadius + 4),
        const SizedBox(height: 16),
        Row(children: const [
          Expanded(child: Skeleton(height: 150, radius: kRadius)),
          SizedBox(width: 12),
          Expanded(child: Skeleton(height: 150, radius: kRadius)),
        ]),
        const SizedBox(height: 12),
        Row(children: const [
          Expanded(child: Skeleton(height: 150, radius: kRadius)),
          SizedBox(width: 12),
          Expanded(child: Skeleton(height: 150, radius: kRadius)),
        ]),
        const SizedBox(height: 16),
        const SkeletonCard(),
      ]);
}
