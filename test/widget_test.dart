import 'package:flutter_test/flutter_test.dart';

import 'package:app_prototype/main.dart';

void main() {
  testWidgets('App shows navigation tabs', (WidgetTester tester) async {
    await tester.pumpWidget(const AtlasBcApp());
    await tester.pump();

    expect(find.text('Camera'), findsOneWidget);
    expect(find.text('Results'), findsOneWidget);
    expect(find.text('Export'), findsOneWidget);
    expect(find.text('ATLAS-BC'), findsOneWidget);
  });
}
