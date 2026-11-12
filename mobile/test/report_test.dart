import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:insightpulse/core/api_client.dart';
import 'package:insightpulse/data/models.dart';
import 'package:insightpulse/features/report_screen.dart';
import 'package:mocktail/mocktail.dart';

import 'support.dart';

final months = ReportMonths(
  months: [(month: '2026-10', label: 'Oct 2026'), (month: '2026-09', label: 'Sep 2026')],
  defaultMonth: '2026-10',
);

Future<void> openReport(WidgetTester tester) async {
  final banner = find.text('Monthly PDF report');
  await tester.scrollUntilVisible(banner, 300);
  await tester.ensureVisible(banner);
  await settle(tester, frames: 3);
  await tester.tap(banner);
  await settle(tester);
}

Finder reportList() => find.descendant(of: find.byType(ReportScreen), matching: find.byType(Scrollable)).first;

Future<void> scrollTo(WidgetTester tester, Finder target) async {
  await tester.scrollUntilVisible(target, 300, scrollable: reportList());
  await settle(tester, frames: 3);
}

void main() {
  testWidgets('Home has quick actions and opens the monthly report', (tester) async {
    final api = defaultApi();
    when(() => api.reportMonths(any())).thenAnswer((_) async => months);
    await pumpApp(tester, api);
    for (final label in ['Ask AI', 'Forecast', 'Customers', 'Report']) {
      expect(find.bySemanticsLabel('Open $label'), findsOneWidget);
    }
    await openReport(tester);
    expect(find.text('Your month in one PDF'), findsOneWidget);
    expect(find.text('Data overview (EDA)'), findsOneWidget);
    await scrollTo(tester, find.text('Create Oct 2026 report'));
    expect(find.text('Create Oct 2026 report'), findsOneWidget);
  });

  testWidgets('the chosen month is built and handed to the share sheet', (tester) async {
    final api = defaultApi();
    final shared = <(int, String)>[];
    when(() => api.reportMonths(any())).thenAnswer((_) async => months);
    when(() => api.monthlyReport(any(), any())).thenAnswer((_) async => Uint8List.fromList(List.filled(2048, 1)));
    await pumpApp(tester, api, fileSharer: (bytes, name, {mimeType = ''}) async => shared.add((bytes.length, name)));
    await openReport(tester);
    await tester.tap(find.text('Sep 2026'));
    await settle(tester);
    final create = find.text('Create Sep 2026 report');
    await scrollTo(tester, create);
    await tester.tap(create);
    await settle(tester);
    verify(() => api.monthlyReport('ds1', '2026-09')).called(1);
    expect(shared.single, (2048, 'InsightPulse-My-shop-2026-09.pdf'));
    expect(find.text('Sep 2026 report is ready'), findsOneWidget);
    await scrollTo(tester, find.text('Share or save'));
    await tester.tap(find.text('Share or save'));
    await settle(tester);
    expect(shared, hasLength(2));
  });

  testWidgets('a server problem is shown on the report screen', (tester) async {
    final api = defaultApi();
    when(() => api.reportMonths(any())).thenAnswer((_) async => months);
    when(() => api.monthlyReport(any(), any())).thenThrow(ApiException('There is no data for Oct 2026.'));
    await pumpApp(tester, api);
    await openReport(tester);
    final create = find.text('Create Oct 2026 report');
    await scrollTo(tester, create);
    await tester.tap(create);
    await settle(tester);
    expect(find.text('There is no data for Oct 2026.'), findsOneWidget);
    expect(find.byIcon(Icons.check_circle_outline), findsNothing);
  });
}
