import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:insightpulse/data/models.dart';
import 'package:mocktail/mocktail.dart';

import 'support.dart';

final generalJson = {
  ...datasetJson,
  'id': 'ds2',
  'name': 'Titanic',
  'filename': 'titanic.csv',
  'row_count': 891,
  'date_min': null,
  'date_max': null,
  'currency': null,
  'kind': 'general',
};

final explorationJson = {
  'dataset_id': 'ds2',
  'overview': {'rows': 891, 'columns': 15, 'missing_cells_pct': 6.5, 'complete_rows_pct': 20.6},
  'quality': {'score': 88, 'label': 'Good', 'issues': <dynamic>[]},
  'columns': [
    {
      'name': 'survived',
      'kind': 'yes/no',
      'missing_pct': 0.0,
      'unique': 2,
      'stats': <dynamic>[],
      'top_values': [
        {'value': '0', 'count': 549, 'share': 61.6},
        {'value': '1', 'count': 342, 'share': 38.4},
      ],
    },
    {
      'name': 'age',
      'kind': 'numeric',
      'missing_pct': 19.9,
      'unique': 88,
      'stats': [
        {'label': 'Median', 'value': '28'},
      ],
      'top_values': <dynamic>[],
    },
  ],
  'charts': [
    {'title': 'survived = 1 by sex', 'caption': 'female: 74% vs male: 19%', 'url': '/api/v1/charts/sex.png'},
  ],
  'insights': [
    {...insightJson('target_rate', 'target', 'Outcome'), 'headline': '38% of rows have survived = 1'},
  ],
  'target': 'survived',
  'predictable': ['survived', 'age'],
};

final predictionJson = {
  'target': 'survived',
  'task': 'classification',
  'metric': 'accuracy',
  'score': 0.79,
  'baseline': 0.62,
  'verdict': 'The model predicts survived correctly 79% of the time.',
  'rows_used': 891,
  'features': [
    {'column': 'who', 'importance': 0.52},
    {'column': 'pclass', 'importance': 0.21},
  ],
  'classes': <dynamic>[],
  'excluded': ['alive'],
  'chart_url': null,
};

MockApi generalApi() {
  final api = defaultApi();
  when(() => api.datasets()).thenAnswer((_) async => [DatasetSummary.fromJson(generalJson)]);
  when(() => api.explore(any(), target: any(named: 'target')))
      .thenAnswer((_) async => Exploration.fromJson(explorationJson));
  when(() => api.predict(any(), any())).thenAnswer((_) async => Prediction.fromJson(predictionJson));
  when(() => api.chartPng(any(), dark: any(named: 'dark'))).thenAnswer((_) async => Uint8List.fromList(tinyPng));
  return api;
}

void main() {
  testWidgets('general data opens Explore on Home, not the sales dashboard', (tester) async {
    final api = generalApi();
    await pumpApp(tester, api);
    expect(find.text('Data exploration'), findsOneWidget);
    expect(find.text('891'), findsOneWidget);
    expect(find.text('38% of rows have survived = 1'), findsWidgets);
    expect(find.text('Outcome to explain'), findsOneWidget);
    expect(find.text('Predict survived'), findsOneWidget);
    verifyNever(() => api.dashboard(any(), any()));
    verifyNever(() => api.recommendations(any()));
  });

  testWidgets('Predict trains on demand and shows what matters', (tester) async {
    final api = generalApi();
    await pumpApp(tester, api);
    final train = find.text('Train a model');
    await tester.ensureVisible(train);
    await tester.tap(train);
    await settle(tester);
    verify(() => api.predict('ds2', 'survived')).called(1);
    expect(find.text('79%'), findsOneWidget);
    expect(find.text('62%'), findsOneWidget);
    expect(find.text('who'), findsOneWidget);
    expect(find.textContaining('Left out alive'), findsOneWidget);
  });

  testWidgets('Forecast explains it is for sales data', (tester) async {
    final api = generalApi();
    await pumpApp(tester, api);
    await tester.tap(find.text('Forecast').last);
    await settle(tester);
    expect(find.text('Forecasts are for sales over time'), findsOneWidget);
  });

  testWidgets('Ask AI suggests questions for any data', (tester) async {
    final api = generalApi();
    await pumpApp(tester, api);
    await tester.tap(find.text('Ask AI').last);
    await settle(tester);
    expect(find.text('Ask about your data'), findsOneWidget);
    expect(find.text('Summarise this dataset in plain words'), findsOneWidget);
  });

  testWidgets('the Data tab shows how the dataset is analysed', (tester) async {
    final api = generalApi();
    when(() => api.profile(any())).thenAnswer(
      (_) async => DatasetProfile.fromJson({...profileJson, 'dataset': generalJson}),
    );
    await pumpApp(tester, api);
    await tester.tap(find.text('Data').last);
    await settle(tester);
    final explore = find.text('Explore this data');
    await tester.scrollUntilVisible(explore, 300);
    expect(find.text('Analyse as'), findsOneWidget);
    expect(find.text('General data'), findsOneWidget);
    expect(explore, findsOneWidget);
    expect(find.byType(SegmentedButton<bool>), findsOneWidget);
  });
}
