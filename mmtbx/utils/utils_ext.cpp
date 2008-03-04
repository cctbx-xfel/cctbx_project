#include <cctbx/boost_python/flex_fwd.h>
#include <boost/python/module.hpp>
#include <boost/python/class.hpp>
#include <boost/python/def.hpp>
#include <boost/python/args.hpp>
#include <mmtbx/utils/utils.h>
#include <scitbx/array_family/boost_python/shared_wrapper.h>
#include <boost/python/return_value_policy.hpp>
#include <boost/python/return_by_value.hpp>

namespace mmtbx { namespace utils {
namespace {

  void init_module()
  {
    using namespace boost::python;
    typedef boost::python::arg arg_;
    typedef return_value_policy<return_by_value> rbv;

    class_<fit_hoh<> >("fit_hoh")
       .def(init<
            cctbx::fractional<> const&,
            cctbx::fractional<> const&,
            cctbx::fractional<> const&,
            cctbx::fractional<> const&,
            cctbx::fractional<> const&,
            double const&,
            cctbx::uctbx::unit_cell const& >((arg_("site_frac_o"),
                                              arg_("site_frac_h1"),
                                              arg_("site_frac_h2"),
                                              arg_("site_frac_peak1"),
                                              arg_("site_frac_peak2"),
                                              arg_("angular_shift"),
                                              arg_("unit_cell"))))
       .add_property("site_cart_o_fitted", make_getter(&fit_hoh<>::site_cart_o_fitted, rbv()))
       .add_property("site_cart_h1_fitted", make_getter(&fit_hoh<>::site_cart_h1_fitted, rbv()))
       .add_property("site_cart_h2_fitted", make_getter(&fit_hoh<>::site_cart_h2_fitted, rbv()))
       .add_property("dist_best", make_getter(&fit_hoh<>::dist_best, rbv()))
    ;
  }

} // namespace <anonymous>
}} // namespace mmtbx::utils

BOOST_PYTHON_MODULE(mmtbx_utils_ext)
{
  mmtbx::utils::init_module();
}
