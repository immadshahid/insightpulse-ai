import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../core/brand.dart';
import '../core/format.dart';
import '../core/theme.dart';

bool _reduceMotion(BuildContext context) => MediaQuery.maybeDisableAnimationsOf(context) ?? false;

/// Icon on a soft tinted rounded square.
class IconBadge extends StatelessWidget {
  const IconBadge({super.key, required this.icon, required this.color, this.size = 36});

  final IconData icon;
  final Color color;
  final double size;

  @override
  Widget build(BuildContext context) => Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          color: color.withValues(alpha: Theme.of(context).brightness == Brightness.dark ? 0.2 : 0.12),
          borderRadius: BorderRadius.circular(size * 0.32),
        ),
        child: Icon(icon, size: size * 0.55, color: color),
      );
}

/// Brand-gradient card with two soft glow circles for depth.
class GradientCard extends StatelessWidget {
  const GradientCard({super.key, required this.child, this.padding = const EdgeInsets.all(20)});

  final Widget child;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    final b = Theme.of(context).brightness;
    return Container(
      decoration: BoxDecoration(
        gradient: Brand.hero(b),
        borderRadius: BorderRadius.circular(kRadius + 4),
        boxShadow: [
          BoxShadow(
            color: Brand.indigo.withValues(alpha: b == Brightness.light ? 0.28 : 0.4),
            blurRadius: 24,
            offset: const Offset(0, 10),
          ),
        ],
      ),
      clipBehavior: Clip.antiAlias,
      child: Stack(children: [
        Positioned(right: -40, top: -50, child: _Glow(size: 160)),
        Positioned(left: -30, bottom: -60, child: _Glow(size: 130, opacity: 0.06)),
        Padding(padding: padding, child: child),
      ]),
    );
  }
}

class _Glow extends StatelessWidget {
  const _Glow({required this.size, this.opacity = 0.1});

  final double size;
  final double opacity;

  @override
  Widget build(BuildContext context) => Container(
        width: size,
        height: size,
        decoration: BoxDecoration(shape: BoxShape.circle, color: Colors.white.withValues(alpha: opacity)),
      );
}

/// Tiny trend line with a soft area fill and an end dot.
class Sparkline extends StatelessWidget {
  const Sparkline({super.key, required this.values, required this.color, this.height = 34});

  final List<double> values;
  final Color color;
  final double height;

  @override
  Widget build(BuildContext context) {
    if (values.length < 2) return SizedBox(height: height);
    return SizedBox(
      height: height,
      width: double.infinity,
      child: CustomPaint(painter: _SparkPainter(values, color, context.palette.card)),
    );
  }
}

class _SparkPainter extends CustomPainter {
  _SparkPainter(this.values, this.color, this.surface);

  final List<double> values;
  final Color color;
  final Color surface;

  @override
  void paint(Canvas canvas, Size size) {
    final lo = values.reduce(math.min);
    final hi = values.reduce(math.max);
    final span = hi - lo == 0 ? 1.0 : hi - lo;
    const pad = 4.0;
    Offset at(int i) => Offset(
          i * (size.width - pad) / (values.length - 1),
          pad + (1 - (values[i] - lo) / span) * (size.height - pad * 2),
        );
    final line = Path()..moveTo(at(0).dx, at(0).dy);
    for (var i = 1; i < values.length; i++) {
      final p0 = at(i - 1), p1 = at(i);
      final mx = (p0.dx + p1.dx) / 2;
      line.cubicTo(mx, p0.dy, mx, p1.dy, p1.dx, p1.dy);
    }
    final area = Path.from(line)
      ..lineTo(at(values.length - 1).dx, size.height)
      ..lineTo(0, size.height)
      ..close();
    canvas.drawPath(
      area,
      Paint()
        ..shader = LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [color.withValues(alpha: 0.28), color.withValues(alpha: 0)],
        ).createShader(Offset.zero & size),
    );
    canvas.drawPath(
      line,
      Paint()
        ..color = color
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2
        ..strokeCap = StrokeCap.round,
    );
    final end = at(values.length - 1);
    canvas.drawCircle(end, 4, Paint()..color = surface);
    canvas.drawCircle(end, 2.8, Paint()..color = color);
  }

  @override
  bool shouldRepaint(_SparkPainter old) => old.values != values || old.color != color;
}

/// Counts up to [value] once, showing [format]ted values, then settles on [finalText].
class CountUpText extends StatelessWidget {
  const CountUpText({super.key, required this.value, required this.format, required this.finalText, this.style});

  final double value;
  final String Function(double) format;
  final String finalText;
  final TextStyle? style;

  @override
  Widget build(BuildContext context) {
    if (_reduceMotion(context)) return Text(finalText, style: style);
    return TweenAnimationBuilder<double>(
      key: ValueKey(finalText),
      tween: Tween(begin: 0, end: 1),
      duration: const Duration(milliseconds: 900),
      curve: Curves.easeOutCubic,
      builder: (context, t, _) => Text(t >= 1 ? finalText : format(value * t), style: style),
    );
  }
}

/// "▲ 4.1%" on a tinted pill: green when up, orange when down, grey when flat or unknown.
class DeltaPill extends StatelessWidget {
  const DeltaPill({super.key, required this.changePct, this.emptyText = 'No earlier data'});

  final double? changePct;
  final String emptyText;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme.labelMedium;
    if (changePct == null) return Text(emptyText, style: t?.copyWith(color: p.muted));
    final flat = changePct!.abs() < 0.5;
    final up = changePct! >= 0;
    final color = flat ? p.muted : (up ? p.positive : p.negative);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(color: color.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(20)),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(flat ? Icons.remove_rounded : (up ? Icons.arrow_upward_rounded : Icons.arrow_downward_rounded),
            size: 14, color: color),
        const SizedBox(width: 2),
        Text(signedPct(changePct!).replaceFirst(RegExp(r'^[+-]'), ''),
            style: t?.copyWith(color: color, fontWeight: FontWeight.w700)),
      ]),
    );
  }
}

/// Horizontal low-expected-high bar for a forecast range.
class RangeBar extends StatelessWidget {
  const RangeBar({super.key, required this.low, required this.mid, required this.high, required this.format,
      this.onGradient = false});

  final double low;
  final double mid;
  final double high;
  final String Function(double) format;
  final bool onGradient;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme.labelMedium;
    final fg = onGradient ? Colors.white : p.text;
    final muted = onGradient ? Colors.white.withValues(alpha: 0.75) : p.muted;
    final pos = high > low ? ((mid - low) / (high - low)).clamp(0.0, 1.0) : 0.5;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      LayoutBuilder(builder: (context, c) {
        return SizedBox(
          height: 18,
          child: Stack(alignment: Alignment.centerLeft, children: [
            Container(
              height: 8,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(8),
                gradient: LinearGradient(colors: [
                  fg.withValues(alpha: 0.25),
                  fg.withValues(alpha: 0.55),
                  fg.withValues(alpha: 0.25),
                ]),
              ),
            ),
            Positioned(
              left: (c.maxWidth - 18) * pos,
              child: Container(
                width: 18,
                height: 18,
                decoration: BoxDecoration(
                  color: fg,
                  shape: BoxShape.circle,
                  border: Border.all(color: onGradient ? Brand.violet : p.card, width: 3),
                ),
              ),
            ),
          ]),
        );
      }),
      const SizedBox(height: 6),
      Row(children: [
        Expanded(child: Text('Low ${format(low)}', style: t?.copyWith(color: muted))),
        const SizedBox(width: 8),
        Expanded(child: Text('High ${format(high)}', textAlign: TextAlign.end, style: t?.copyWith(color: muted))),
      ]),
    ]);
  }
}

/// Animated ring gauge (0-100) with content in the middle.
class RingGauge extends StatelessWidget {
  const RingGauge({super.key, required this.value, required this.color, required this.child, this.size = 96});

  final double value;
  final Color color;
  final Widget child;
  final double size;

  @override
  Widget build(BuildContext context) {
    final track = context.palette.border;
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: _reduceMotion(context) ? value : 0, end: value),
      duration: const Duration(milliseconds: 1000),
      curve: Curves.easeOutCubic,
      builder: (context, v, _) => SizedBox(
        width: size,
        height: size,
        child: CustomPaint(
          painter: _RingPainter(v / 100, color, track),
          child: Center(child: child),
        ),
      ),
    );
  }
}

class _RingPainter extends CustomPainter {
  _RingPainter(this.fraction, this.color, this.track);

  final double fraction;
  final Color color;
  final Color track;

  @override
  void paint(Canvas canvas, Size size) {
    const stroke = 9.0;
    final rect = Offset.zero & size;
    final arc = rect.deflate(stroke / 2);
    canvas.drawArc(arc, 0, math.pi * 2, false,
        Paint()..color = track..style = PaintingStyle.stroke..strokeWidth = stroke);
    canvas.drawArc(
      arc,
      -math.pi / 2,
      math.pi * 2 * fraction,
      false,
      Paint()
        ..shader = SweepGradient(
          startAngle: -math.pi / 2,
          endAngle: math.pi * 1.5,
          colors: [color.withValues(alpha: 0.6), color],
          transform: const GradientRotation(-math.pi / 2),
        ).createShader(rect)
        ..style = PaintingStyle.stroke
        ..strokeWidth = stroke
        ..strokeCap = StrokeCap.round,
    );
  }

  @override
  bool shouldRepaint(_RingPainter old) => old.fraction != fraction || old.color != color;
}

/// Gradient circle with the AI spark: the assistant's avatar.
class AiAvatar extends StatelessWidget {
  const AiAvatar({super.key, this.size = 32});

  final double size;

  @override
  Widget build(BuildContext context) => Container(
        width: size,
        height: size,
        decoration: BoxDecoration(shape: BoxShape.circle, gradient: Brand.hero(Theme.of(context).brightness)),
        child: Icon(Icons.auto_awesome, size: size * 0.55, color: Colors.white),
      );
}

/// Three bouncing dots: "the assistant is working".
class TypingDots extends StatefulWidget {
  const TypingDots({super.key});

  @override
  State<TypingDots> createState() => _TypingDotsState();
}

class _TypingDotsState extends State<TypingDots> with SingleTickerProviderStateMixin {
  late final AnimationController _c =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 1100))..repeat();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final color = context.palette.muted;
    return Semantics(
      label: 'Working on your answer',
      child: AnimatedBuilder(
        animation: _c,
        builder: (context, _) => Row(mainAxisSize: MainAxisSize.min, children: [
          for (var i = 0; i < 3; i++)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 3),
              child: Transform.translate(
                offset: Offset(0, -4 * math.max(0, math.sin((_c.value - i * 0.18) * math.pi * 2))),
                child: Container(width: 8, height: 8, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
              ),
            ),
        ]),
      ),
    );
  }
}
