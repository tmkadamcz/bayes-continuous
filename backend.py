import math
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats
from scipy import integrate
from scipy import optimize
import time
import decimal
import json
import mpld3

class Posterior_scipyrv(stats.rv_continuous):
	def __init__(self, distribution1, distribution2):
		super(Posterior_scipyrv, self).__init__()

		self.distribution1= distribution1
		self.distribution2= distribution2

		self.cdf_lookup = {} # Lookup table to increase speed

		'''
		defining the support of the product pdf is important
		because, when we use a numerical equation solver on the CDF,
		it will only need to look for solutions in the support, instead
		of on the entire real line.
		'''
		a1, b1 = distribution1.support()
		a2,b2 = distribution2.support()

		# SciPy calls the support (a,b)
		self.a , self.b = intersect_intervals([(a1,b1),(a2,b2)])

		'''
		the mode is used in my custom definition of _cdf() below.
		it's important that we don't run optimize.fmin every time cdf 
		is called, so I run it during init.
		'''
		initial_guess_for_mode = (self.distribution1.expect() + self.distribution2.expect()) / 2 # could be improved
		self.mode = initial_guess_for_mode

		'''find normalization constant in init, so don't have to run integration every time'''
		self.normalization_constant = split_integral(function_to_integrate=self.unnormalized_pdf,
													 splitpoint=self.mode,
													 integrate_to=self.b,
													 support=self.support())


	def unnormalized_pdf(self,x):
		return self.distribution1.pdf(x) * self.distribution2.pdf(x)

	def _pdf(self,x):
		return self.unnormalized_pdf(x)/self.normalization_constant

	def _cdf(self,x):
		# Memeoization: we consider the cdf to be 1 forevermore once it reaches values close to 1
		round_to_places = 5
		for x_lookup in self.cdf_lookup:
			cdf_value_approximate = np.around(self.cdf_lookup[x_lookup], round_to_places)
			if x_lookup < x and cdf_value_approximate==1.0:
				return 1

		# Memeoization for any input: check lookup table for largest integral already computed below x. only
		# integrate the remaining bit.
		# Same number of integrations, but the integrations are over a much smaller interval.
		sortedkeys = sorted(self.cdf_lookup, reverse=True)
		for key in sortedkeys:
			# find the greatest key less than x
			if key<x:
				cdf_value = self.cdf_lookup[key]+integrate.quad(self.pdf,key,x)[0] #integrate smaller interval
				self.cdf_lookup[float(x)] = cdf_value  # add to lookup table
				return cdf_value

		cdf_value = split_integral(
			function_to_integrate=self.pdf,
			splitpoint=self.mode,
			integrate_to=x,
			support=self.support())

		self.cdf_lookup[float(x)] = cdf_value  # add to lookup table
		return cdf_value

	def ppf_with_bounds(self, quantile, leftbound, rightbound):
		'''
		wraps scipy ppf function
		https://github.com/scipy/scipy/blob/4c0fd79391e3b2ec2738bf85bb5dab366dcd12e4/scipy/stats/_distn_infrastructure.py#L1681-L1699
		'''

		factor = 10.
		left, right = self._get_support()

		if np.isinf(left):
			left = min(-factor, right)
			while self._ppf_to_solve(left, quantile) > 0.:
				left, right = left * factor, left
		# left is now such that cdf(left) <= q
		# if right has changed, then cdf(right) > q

		if np.isinf(right):
			right = max(factor, left)
			while self._ppf_to_solve(right, quantile) < 0.:
				left, right = right, right * factor
		# right is now such that cdf(right) >= q

		# This is where we add the bounds to ppf copied from above
		if leftbound is not None:
			left = leftbound
		if rightbound is not None:
			right = rightbound

		return optimize.brentq(self._ppf_to_solve, left, right, args=quantile, xtol=self.xtol, full_output=False)


	def compute_percentiles(self, percentiles_list):
		result = {}

		start = time.time()
		print('Running compute_percentiles_exact. Support: ', self.support())

		percentiles_list.sort()
		percentiles_reordered = sum(zip(percentiles_list,reversed(percentiles_list)), ())[:len(percentiles_list)] #https://stackoverflow.com/a/17436999/8010877

		def get_bounds_on_ppf(existing_results, percentile):
			keys = list(existing_results.keys())
			keys.append(percentile)
			keys.sort()
			i = keys.index(percentile)
			if i != 0:
				leftbound = existing_results[keys[i - 1]]
			else:
				leftbound = None
			if i != len(keys) - 1:
				rightbound = existing_results[keys[i + 1]]
			else:
				rightbound = None
			return leftbound, rightbound

		for p in percentiles_reordered:
			print("trying to compute the", p, "th percentile")
			try:
				leftbound , rightbound = get_bounds_on_ppf(result,p)
				res = self.ppf_with_bounds(p,leftbound,rightbound)
				result[p] = res
			except RuntimeError as e:
				result[p] = e

		sorted_result = {key:value for key,value in sorted(result.items())}

		end = time.time()
		description_string = 'Computed in ' + str(np.around(end - start, 1)) + ' seconds'

		return {'result': sorted_result, 'runtime': description_string}

class CustomFromPDF(stats.rv_continuous):
	def __init__(self, pdf_callable,a=-np.inf,b=np.inf):
		super(CustomFromPDF, self).__init__()
		self.pdf_callable = pdf_callable
		self.a = a
		self.b = b

	def _pdf(self,x):
		return self.pdf_callable(x)

def graph_out(user_inputs):
	plt.rcParams.update({'font.size': 16})
	# parse inputs
	prior = user_inputs['prior']
	likelihood = user_inputs['likelihood']
	override_graph_range = user_inputs['override_graph_range']

	# compute posterior pdf
	s = time.time()
	posterior = Posterior_scipyrv(prior, likelihood)
	e = time.time()
	print(e - s, 'seconds to get posterior pdf')

	# Plot
	if override_graph_range:
		x_from, x_to = override_graph_range
	else:
		x_from, x_to = intelligently_set_graph_domain(prior, likelihood)

	s = time.time()
	plot = plot_pdfs_bayes_update(prior, likelihood, posterior, x_from=x_from, x_to=x_to)
	plot = mpld3.fig_to_html(plot)
	e = time.time()
	print(e - s, 'seconds to make plot')

	# Expected value
	ev = np.around(posterior.expect(), 2)
	ev_string = 'Posterior expected value: ' + str(ev) + '<br>'

	return plot + ev_string

def percentiles_out(user_inputs):
	# Parse inputs
	prior = user_inputs['prior']
	likelihood = user_inputs['likelihood']

	# compute posterior pdf
	posterior = Posterior_scipyrv(prior, likelihood)

	# percentiles
	percentiles_exact_string = ''

	if user_inputs['custom_percentiles']:
		p = user_inputs['custom_percentiles']
	else:
		p = [0.1, 0.25, 0.5, 0.75, 0.9]
	percentiles_exact = posterior.compute_percentiles(p)

	percentiles_exact_string = percentiles_exact['runtime'] + '<br>'
	for x in percentiles_exact['result']:
		percentiles_exact_string += str(x) + ', ' + str(np.around(percentiles_exact['result'][x], 2)) + '<br>'
	return percentiles_exact_string

def intersect_intervals(two_tuples):
	interval1 , interval2 = two_tuples

	interval1_left,interval1_right = interval1
	interval2_left,interval2_right = interval2

	if interval1_right < interval2_left or interval2_right < interval2_left:
		raise ValueError("the distributions have no overlap")
	
	intersect_left,intersect_right = max(interval1_left,interval2_left),min(interval1_right,interval2_right)

	return intersect_left,intersect_right

def extremeties_intervals(two_tuples):
	interval1,interval2 = two_tuples

	interval1_left, interval1_right = interval1
	interval2_left, interval2_right = interval2

	extreme_left = min(interval1_left,interval1_right,interval2_left,interval2_right)
	extreme_right = max(interval1_left,interval1_right,interval2_left,interval2_right)

	return extreme_left,extreme_right

def split_integral(function_to_integrate,splitpoint,integrate_to,support=(-np.inf,np.inf)):
	'''
	https://stackoverflow.com/questions/47193045/why-does-integrate-quadlambda-x-xexp-x2-2-sqrt2pi-0-0-100000-give-0
	https://stackoverflow.com/questions/34877147/limits-of-quad-integration-in-scipy-with-np-inf

	if you try

	for x in range(100):
		print('cdf(',x,') = ',distr.cdf(x))

	CDF goes to 1 and then becomes
	a tiny value or 0. Due to problem of integrating over an area that
	is mostly 0. See stackoverflow links above.

	This creates problems when trying to use numerical equation solvers
	on the CDF. e.g. a bisection algo will first try CDF(very_large_number)
	and this will return 0.

	you can point quad to the region of the function
	where the peak(s) is/are with by supplying the points argument
	(points where 'where local difficulties of the integrand may occur'
	according to the documentation)

	But you can't pass points when one of the integration bounds
	is infinite.

	My solution: do the integration in two parts.
	First the left, then the right.
	Won't work for every function, but should cover many cases.
	'''
	support_left,support_right = support

	if integrate_to < splitpoint:
		# just return the integral normally
		return integrate.quad(function_to_integrate,support_left,integrate_to)[0] #only return the answer, first element in tuple. Same below.

	else:
		integral_left = integrate.quad(function_to_integrate, support_left, splitpoint)[0]
		integral_right = integrate.quad(function_to_integrate, splitpoint, integrate_to)[0]
		return integral_left + integral_right

def plot_pdfs(dict_of_dists,x_from,x_to):
	x_from ,x_to = float(x_from),float(x_to)
	x = np.linspace(x_from,x_to,100)

	figure, axes = plt.subplots()
	for dist in dict_of_dists:
		axes.plot(x,dict_of_dists[dist].pdf(x),label=dist)
	axes.legend()
	axes.set_xlabel("θ")
	axes.set_ylabel("Probability density")
	return figure

def plot_pdfs_bayes_update(prior,likelihood,posterior,x_from=-50,x_to=50):
	prior_string = "f₀(θ) = P(θ)"
	likelihood_string = "f₁(θ) = P(E|θ)"
	posterior_string = "P(θ|E)"

	plot = plot_pdfs({prior_string:prior, likelihood_string:likelihood, posterior_string:posterior},
					x_from,
					x_to)
	return plot

def intelligently_set_graph_domain(prior,likelihood):
	p = 0.1
	prior_range = prior.ppf(p), prior.ppf(1-p)
	likelihood_range = likelihood.ppf(p), likelihood.ppf(1-p)

	ranges = extremeties_intervals([prior_range,likelihood_range])

	posterior_support = intersect_intervals([prior.support(),likelihood.support()])

	domain = intersect_intervals([posterior_support,ranges])

	buffer = 0.1
	buffer = abs(buffer*(domain[1]-domain[0]))
	domain = domain[0]-buffer,domain[1]+buffer

	return domain

