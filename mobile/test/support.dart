import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:insightpulse/app.dart';
import 'package:insightpulse/core/api_client.dart';
import 'package:insightpulse/core/google_auth.dart';
import 'package:insightpulse/core/prefs.dart';
import 'package:insightpulse/core/share.dart';
import 'package:insightpulse/data/api.dart';
import 'package:insightpulse/data/models.dart';
import 'package:insightpulse/state/providers.dart';
import 'package:mocktail/mocktail.dart';

class MockApi extends Mock implements InsightPulseApi {}

final tinyPng = base64Decode(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
);

final datasetJson = {
  'id': 'ds1',
  'name': 'My shop',
  'filename': 'sales.csv',
  'status': 'ready',
  'row_count': 28420,
  'version': 1,
  'created_at': '2026-11-05T10:00:00Z',
  'quality_score': 98,
  'date_min': '2025-05-01',
  'date_max': '2026-10-31',
  'currency': 'PKR',
};

Map<String, dynamic> dashboardJson({String forecast = 'ready', String summaryStatus = 'off'}) => {
  'dataset_id': 'ds1',
  'period': '30d',
  'currency': 'PKR',
  'window': {'start': '2026-10-02', 'end': '2026-10-31', 'prev_start': '2026-09-02', 'prev_end': '2026-10-01'},
  'kpis': [
    {
      'key': 'revenue',
      'label': 'Revenue',
      'value': 10.6e6,
      'display': 'PKR 10.6M',
      'previous': 10.5e6,
      'change_pct': 1.0,
      'direction': 'up',
      'spark': [3, 5, 4, 6, 8, 7, 9],
    },
    {
      'key': 'orders',
      'label': 'Orders',
      'value': 1388,
      'display': '1,388',
      'previous': 1373,
      'change_pct': 1.1,
      'direction': 'up',
      'spark': [3, 5, 4, 6, 8, 7, 9],
    },
    {
      'key': 'avg_order_value',
      'label': 'Avg order value',
      'value': 7600,
      'display': 'PKR 7.6K',
      'previous': 7900,
      'change_pct': -3.9,
      'direction': 'down',
      'spark': [3, 5, 4, 6, 8, 7, 9],
    },
    {
      'key': 'active_customers',
      'label': 'Active customers',
      'value': 679,
      'display': '679',
      'previous': null,
      'change_pct': null,
      'direction': null,
      'spark': [3, 5, 4, 6, 8, 7, 9],
    },
  ],
  'ai_summary': {
    'text': 'Revenue was PKR 10.6M over the last 30 days, up 1.0% on the period before.',
    'source': 'template',
    'status': summaryStatus,
  },
  'top_insights': [insightJson('anomalies', 'anomalies', 'Anomaly')],
  'charts': {'revenue_trend': '/api/v1/charts/trend.png'},
  'forecast': {
    'status': forecast,
    'job_id': 'j1',
    'model': 'prophet',
    'accuracy_note': 'Within ±9% on the last 4 months',
  },
};

Map<String, dynamic> insightJson(String id, String category, String tag) => {
  'id': id,
  'kind': id,
  'category': category,
  'tag': tag,
  'headline': 'Headline for $id',
  'why_it_matters': 'Why $id matters.',
  'score': 0.7,
  'data': <String, dynamic>{},
  'chart_url': '/api/v1/charts/$id.png',
  'narrative': null,
};

final profileJson = {
  'dataset': datasetJson,
  'profile': {
    'row_count': 28515,
    'column_count': 3,
    'columns': [
      {
        'name': 'Order Date',
        'kind': 'datetime',
        'missing_pct': 0.1,
        'unique_count': 900,
        'sample_values': ['2025-05-01 01:46'],
      },
      {
        'name': 'Total',
        'kind': 'numeric',
        'missing_pct': 0.1,
        'unique_count': 900,
        'sample_values': ['3296.0'],
      },
      {
        'name': 'City',
        'kind': 'categorical',
        'missing_pct': 0.2,
        'unique_count': 4,
        'sample_values': ['Karachi'],
      },
    ],
  },
  'mapping': {
    'date': 'Order Date',
    'revenue': 'Total',
    'quantity': null,
    'product': null,
    'customer': null,
    'region': 'City',
    'order_id': null,
    'confidence': {},
    'source': 'llm',
  },
  'roles': ['date', 'revenue', 'quantity', 'product', 'customer', 'region', 'order_id'],
  'required_roles': ['date', 'revenue'],
  'quality': {
    'score': 98,
    'label': 'Excellent',
    'issues': [
      {'severity': 'info', 'message': '40 rows were exact duplicates and were removed.'},
    ],
  },
  'cleaning': null,
};

/// A mock API with sensible defaults for a logged-in user with one dataset.
MockApi defaultApi() {
  final api = MockApi();
  when(() => api.datasets()).thenAnswer((_) async => [DatasetSummary.fromJson(datasetJson)]);
  when(() => api.dashboard(any(), any())).thenAnswer((_) async => Dashboard.fromJson(dashboardJson()));
  when(() => api.churn(any())).thenAnswer(
    (_) async => const ChurnReport(
      customersScored: 500,
      revenueAtRisk: 2.5e6,
      riskBands: {'high': 40, 'medium': 100, 'low': 360},
      topAtRisk: [AtRiskCustomer(customer: 'Noor Ansari', probability: 0.91, recencyDays: 120, revenueLast365: 84000)],
    ),
  );
  when(() => api.segments(any())).thenAnswer(
    (_) async => const [
      CustomerSegment(name: 'Champions', customers: 120, revenueShare: 0.72, avgRecencyDays: 9, avgSpend: 90000),
    ],
  );
  when(() => api.recommendations(any())).thenAnswer(
    (_) async => [Recommendation(title: 'Win back quiet customers', detail: 'Send an offer.', impact: 'high')],
  );
  when(() => api.insights(any(), category: any(named: 'category'))).thenAnswer(
    (_) async => InsightFeed(
      items: [
        Insight.fromJson(insightJson('anomalies', 'anomalies', 'Anomaly')),
        Insight.fromJson(insightJson('top_products', 'products', 'Products')),
      ],
      narratives: 'off',
    ),
  );
  when(() => api.profile(any())).thenAnswer((_) async => DatasetProfile.fromJson(profileJson));
  when(() => api.chartPng(any(), dark: any(named: 'dark'))).thenAnswer((_) async => Uint8List.fromList(tinyPng));
  return api;
}

Future<void> pumpApp(
  WidgetTester tester,
  MockApi api, {
  bool loggedIn = true,
  MemoryPrefs? prefs,
  double textScale = 1,
  Sharer? sharer,
  GoogleAuth google = const GoogleAuthUnavailable(),
}) async {
  tester.view.physicalSize = const Size(1170, 2532); // phone, 390 x 844 logical
  tester.view.devicePixelRatio = 3;
  tester.platformDispatcher.textScaleFactorTestValue = textScale;
  addTearDown(tester.view.reset);
  addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
  await tester.pumpWidget(
    ProviderScope(
      retry: (_, _) => null,
      overrides: [
        apiProvider.overrideWithValue(api),
        prefsProvider.overrideWithValue(prefs ?? MemoryPrefs({'onboarded': '1'})),
        sharerProvider.overrideWithValue(sharer ?? (text, {subject}) async {}),
        googleAuthProvider.overrideWithValue(google),
        tokenStoreProvider.overrideWithValue(
          loggedIn ? MemoryTokenStore(token: 't', email: 'ayesha.khan@example.com') : MemoryTokenStore(),
        ),
      ],
      child: const InsightPulseApp(googleFonts: false),
    ),
  );
  await settle(tester);
}

/// Like pumpAndSettle, but tolerates endless skeleton/spinner animations.
/// Pumps 1.6 s of frames: long enough for entrance and count-up animations
/// (pumpAndSettle never returns while a shimmer or typing indicator repeats).
Future<void> settle(WidgetTester tester, {int frames = 16}) async {
  for (var i = 0; i < frames; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

ApiException unavailable() => ApiException('Ask AI needs an AI key.', status: 503);
