import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/format.dart';
import '../core/theme.dart';
import '../state/providers.dart';

/// White (or dark) card with the 1px border and 18px radius.
class AppCard extends StatelessWidget {
  const AppCard({super.key, required this.child, this.padding = const EdgeInsets.all(16), this.color, this.onTap});

  final Widget child;
  final EdgeInsetsGeometry padding;
  final Color? color;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final card = Card(
      color: color,
      clipBehavior: Clip.antiAlias,
      child: onTap == null
          ? Padding(padding: padding, child: child)
          : InkWell(onTap: onTap, child: Padding(padding: padding, child: child)),
    );
    return card;
  }
}

class SectionTitle extends StatelessWidget {
  const SectionTitle(this.text, {super.key, this.trailing});

  final String text;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 8, bottom: 10),
        child: Row(children: [
          Expanded(
            child: Text(text,
                style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
          ),
          ?trailing,
        ]),
      );
}

/// Shimmering placeholder block used while content loads.
class Skeleton extends StatefulWidget {
  const Skeleton({super.key, this.height = 16, this.width, this.radius = 10});

  final double height;
  final double? width;
  final double radius;

  @override
  State<Skeleton> createState() => _SkeletonState();
}

class _SkeletonState extends State<Skeleton> with SingleTickerProviderStateMixin {
  late final AnimationController _c =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 1400))..repeat();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final base = p.border;
    final shine = Color.lerp(p.border, p.card, 0.7)!;
    return AnimatedBuilder(
      animation: _c,
      builder: (context, _) {
        // A soft highlight band sweeps left to right.
        final x = _c.value * 3 - 1.5;
        return Container(
          height: widget.height,
          width: widget.width,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(widget.radius),
            gradient: LinearGradient(
              begin: Alignment(x - 1, -0.3),
              end: Alignment(x + 1, 0.3),
              colors: [base, shine, base],
              stops: const [0.25, 0.5, 0.75],
            ),
          ),
        );
      },
    );
  }
}

/// A card-shaped skeleton for lists and feeds.
class SkeletonCard extends StatelessWidget {
  const SkeletonCard({super.key, this.chart = true});

  final bool chart;

  @override
  Widget build(BuildContext context) => AppCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Skeleton(height: 14, width: 90),
          const SizedBox(height: 12),
          const Skeleton(height: 18),
          const SizedBox(height: 8),
          const Skeleton(height: 18, width: 200),
          if (chart) ...[const SizedBox(height: 14), const AspectRatio(aspectRatio: 1200 / 680, child: Skeleton(radius: 12))],
        ]),
      );
}

class EmptyState extends StatelessWidget {
  const EmptyState({super.key, required this.icon, required this.title, required this.message, this.action, this.onAction});

  final IconData icon;
  final String title;
  final String message;
  final String? action;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Container(
            padding: const EdgeInsets.all(18),
            decoration: BoxDecoration(color: p.accentSoft, shape: BoxShape.circle),
            child: Icon(icon, size: 34, color: p.accent),
          ),
          const SizedBox(height: 18),
          Text(title, textAlign: TextAlign.center, style: t.titleLarge?.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(height: 8),
          Text(message, textAlign: TextAlign.center, style: t.bodyMedium?.copyWith(color: p.muted)),
          if (action != null) ...[
            const SizedBox(height: 20),
            FilledButton(onPressed: onAction, child: Text(action!)),
          ],
        ]),
      ),
    );
  }
}

class ErrorState extends StatelessWidget {
  const ErrorState({super.key, required this.error, this.onRetry});

  final Object error;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) => EmptyState(
        icon: Icons.cloud_off_outlined,
        title: 'Something went wrong',
        message: '$error',
        action: onRetry == null ? null : 'Try again',
        onAction: onRetry,
      );
}

/// Inline error used inside a card (keeps the rest of the screen usable).
class InlineError extends StatelessWidget {
  const InlineError(this.message, {super.key, this.onRetry});

  final String message;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Row(children: [
      Icon(Icons.error_outline, color: p.negative),
      const SizedBox(width: 10),
      Expanded(child: Text(message, style: TextStyle(color: p.muted))),
      if (onRetry != null) TextButton(onPressed: onRetry, child: const Text('Retry')),
    ]);
  }
}

/// Server-rendered chart PNG in the current theme (fetched with the auth header).
/// Tap to open it full screen with pinch-to-zoom.
class ChartImage extends ConsumerWidget {
  const ChartImage(this.url, {super.key, this.semanticLabel, this.title});

  final String url;
  final String? semanticLabel;

  /// Shown in the full-screen viewer's app bar.
  final String? title;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    final key = (url: url, dark: dark);
    final png = ref.watch(chartBytesProvider(key));
    final p = context.palette;
    return AspectRatio(
      aspectRatio: 1200 / 680,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(12),
        child: png.when(
          data: (bytes) => Semantics(
            button: true,
            label: '${semanticLabel ?? title ?? 'Chart'}. Open full screen',
            excludeSemantics: true,
            child: Material(
              color: Colors.transparent,
              child: InkWell(
                onTap: () {
                  HapticFeedback.selectionClick();
                  Navigator.of(context, rootNavigator: true).push(MaterialPageRoute<void>(
                    fullscreenDialog: true,
                    builder: (_) => ChartViewer(url: url, title: title ?? semanticLabel ?? 'Chart'),
                  ));
                },
                child: Stack(fit: StackFit.expand, children: [
                  Image.memory(bytes, fit: BoxFit.contain, gaplessPlayback: true),
                  Positioned(
                    right: 6,
                    top: 6,
                    child: Container(
                      padding: const EdgeInsets.all(5),
                      decoration: BoxDecoration(
                        color: p.card.withValues(alpha: 0.85),
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: p.border),
                      ),
                      child: Icon(Icons.open_in_full_rounded, size: 14, color: p.muted),
                    ),
                  ),
                ]),
              ),
            ),
          ),
          loading: () => const Skeleton(radius: 12),
          error: (e, _) => Center(
            child: TextButton.icon(
              onPressed: () => ref.invalidate(chartBytesProvider(key)),
              icon: const Icon(Icons.refresh),
              label: const Text('Chart failed to load. Retry'),
            ),
          ),
        ),
      ),
    );
  }
}

/// Full-screen chart with pinch-to-zoom (rotate the phone for a wider view).
class ChartViewer extends ConsumerWidget {
  const ChartViewer({super.key, required this.url, required this.title});

  final String url;
  final String title;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    final png = ref.watch(chartBytesProvider((url: url, dark: dark)));
    final p = context.palette;
    return Scaffold(
      backgroundColor: p.card,
      appBar: AppBar(
        backgroundColor: p.card,
        title: Text(title, style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
        leading: IconButton(
          tooltip: 'Close',
          icon: const Icon(Icons.close_rounded),
          onPressed: () => Navigator.of(context).pop(),
        ),
      ),
      body: SafeArea(
        child: Column(children: [
          Expanded(
            child: png.when(
              data: (bytes) => InteractiveViewer(
                maxScale: 5,
                child: Center(child: Image.memory(bytes, fit: BoxFit.contain, semanticLabel: title)),
              ),
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (e, _) => Center(child: Text('$e')),
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(12),
            child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
              Icon(Icons.pinch_outlined, size: 16, color: p.muted),
              const SizedBox(width: 6),
              Flexible(
                child: Text('Pinch to zoom · rotate for a wider view',
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.labelMedium?.copyWith(color: p.muted)),
              ),
            ]),
          ),
        ]),
      ),
    );
  }
}

/// "+4.1%" with an up/down arrow, green when good and orange when bad.
class DeltaLabel extends StatelessWidget {
  const DeltaLabel({super.key, required this.changePct, this.suffix});

  final double? changePct;
  final String? suffix;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme.labelMedium;
    if (changePct == null) return Text('No earlier data', style: t?.copyWith(color: p.muted));
    final up = changePct! >= 0;
    final color = changePct!.abs() < 0.5 ? p.muted : (up ? p.positive : p.negative);
    return Row(mainAxisSize: MainAxisSize.min, children: [
      Icon(up ? Icons.arrow_upward_rounded : Icons.arrow_downward_rounded, size: 16, color: color),
      const SizedBox(width: 2),
      Text(signedPct(changePct!).replaceFirst(RegExp(r'^[+-]'), ''),
          style: t?.copyWith(color: color, fontWeight: FontWeight.w700)),
      if (suffix != null) Flexible(child: Text(' $suffix', style: t?.copyWith(color: p.muted))),
    ]);
  }
}

/// Small rounded label (tags, badges).
class Pill extends StatelessWidget {
  const Pill(this.text, {super.key, this.color, this.background, this.icon});

  final String text;
  final Color? color;
  final Color? background;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final fg = color ?? p.accent;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(color: background ?? p.accentSoft, borderRadius: BorderRadius.circular(20)),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        if (icon != null) ...[Icon(icon, size: 14, color: fg), const SizedBox(width: 4)],
        Flexible(
          child: Text(text,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.labelSmall?.copyWith(color: fg, fontWeight: FontWeight.w700)),
        ),
      ]),
    );
  }
}
